"""Investigación web de la razón social del beneficiario.

Dada la razón social extraída del correo, usa la **búsqueda web nativa del
modelo** (OpenAI web search vía la Responses API) para inferir a qué se dedica la
empresa. El modelo busca en la web y sintetiza una descripción con sus fuentes;
no se usa ningún proveedor de búsqueda aparte. El resultado (`WebFindings`)
alimenta al `comparador` (flag de discrepancia), al `code_resolver` (contexto de
apoyo) y a la `justificacion`.

La función de búsqueda se inyecta vía `search` para poder testear sin red ni
API key: `search(razon_social) -> dict` debe devolver
`{"resumen": str, "fuentes": list[str]}`.

Si falta la llave de OpenAI, la búsqueda falla o no hay resultados, `found` queda
en `False` y el flujo degrada sin romperse (nunca lanza).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from ..logging_conf import get_logger
from ..settings import get_settings

logger = get_logger(__name__)

# `search(razon_social)` -> {"resumen": str, "fuentes": list[str]}. Inyectable.
SearchFn = Callable[[str], dict[str, Any]]

# Cuántas fuentes/URLs se conservan y cuánto se recorta el texto de la web.
MAX_FUENTES = 5
MAX_RESUMEN_CHARS = 1500


class WebFindings(BaseModel):
    """Lo que la web dice sobre la empresa. Insumo de apoyo, nunca autoritativo."""

    razon_social: str
    found: bool = False
    resumen: str = ""  # descripción de a qué se dedica la empresa (sintetizada)
    fuentes: list[str] = Field(default_factory=list)  # URLs citadas por el modelo
    sitio_oficial: str | None = None  # primera fuente (aprox. sitio oficial)
    contenido_web: str = ""  # texto de apoyo para la justificación (= resumen)


def lookup_company(razon_social: str, search: SearchFn | None = None) -> WebFindings:
    """Investiga la razón social en la web y resume la actividad de la empresa."""
    razon = (razon_social or "").strip()
    if not razon:
        return WebFindings(razon_social="", found=False)

    _search = search or _default_search
    try:
        raw = _search(razon)
    except Exception as e:  # noqa: BLE001
        logger.warning("web_lookup.search_failed", razon_social=razon, error=str(e))
        return WebFindings(razon_social=razon, found=False)

    resumen = _truncate(str(raw.get("resumen") or "").strip(), MAX_RESUMEN_CHARS)
    fuentes = [str(u) for u in (raw.get("fuentes") or []) if u][:MAX_FUENTES]
    found = bool(resumen)
    if not found:
        logger.info("web_lookup.sin_resultados", razon_social=razon)
    return WebFindings(
        razon_social=razon,
        found=found,
        resumen=resumen,
        fuentes=fuentes,
        sitio_oficial=fuentes[0] if fuentes else None,
        contenido_web=resumen,
    )


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _default_search(razon_social: str) -> dict[str, Any]:
    """Búsqueda real con la web search de OpenAI (Responses API + tool web_search)."""
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    prompt = (
        f"Investiga en la web la empresa «{razon_social}» (Colombia, sector "
        "agropecuario). En 4 a 6 frases resume a qué se dedica, sus líneas de "
        "negocio y su ubicación. Si no encuentras información confiable de esta "
        "empresa en particular, dilo explícitamente y no inventes."
    )
    response = client.responses.create(
        model=settings.web_search_model,
        tools=[{"type": "web_search"}],
        input=prompt,
    )
    return {
        "resumen": (getattr(response, "output_text", None) or "").strip(),
        "fuentes": _citas(response),
    }


def _citas(response: Any) -> list[str]:
    """Extrae las URLs citadas (annotations `url_citation`) de la respuesta."""
    urls: list[str] = []
    for item in getattr(response, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            for ann in getattr(block, "annotations", None) or []:
                url = getattr(ann, "url", None)
                if url:
                    urls.append(str(url))
    return list(dict.fromkeys(urls))
