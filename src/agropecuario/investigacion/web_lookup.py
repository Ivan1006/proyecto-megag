"""Búsqueda web de la razón social del beneficiario (Tavily).

Dada la razón social extraída del correo, busca en la web para inferir a qué se
dedica la empresa. El resultado (`WebFindings`) alimenta al `comparador` (para el
flag de discrepancia) y al `code_resolver` (como contexto de apoyo).

La función de búsqueda se inyecta vía `search` para poder testear sin red ni
API key: `search(query) -> dict` debe devolver la respuesta con forma Tavily
(`{"answer": str | None, "results": [{"url", "title", "content"}, ...]}`).

Si falta la llave, la búsqueda falla o no hay resultados, `found` queda en
`False` y el flujo degrada sin romperse (nunca lanza).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from ..logging_conf import get_logger
from ..settings import get_settings

logger = get_logger(__name__)

# `search(query)` -> respuesta con forma Tavily. Inyectable para tests.
SearchFn = Callable[[str], dict[str, Any]]

# Cuántas fuentes/URLs se conservan y cuánto se recorta el resumen del contexto.
MAX_FUENTES = 5
MAX_RESUMEN_CHARS = 1200
# El contenido crudo del sitio (para redactar la justificación) se recorta más largo.
MAX_CONTENIDO_CHARS = 4000


class WebFindings(BaseModel):
    """Lo que la web dice sobre la empresa. Insumo de apoyo, nunca autoritativo."""

    razon_social: str
    found: bool = False
    resumen: str = ""  # texto que describe a qué se dedica la empresa
    fuentes: list[str] = Field(default_factory=list)  # URLs consultadas
    sitio_oficial: str | None = None  # URL que parece el sitio oficial de la empresa
    contenido_web: str = ""  # texto extraído del sitio (insumo de la justificación)


def lookup_company(razon_social: str, search: SearchFn | None = None) -> WebFindings:
    """Busca la razón social en la web y resume la actividad de la empresa."""
    razon = (razon_social or "").strip()
    if not razon:
        return WebFindings(razon_social="", found=False)

    _search = search or _default_search
    query = (
        f'"{razon}" empresa Colombia a qué se dedica actividad económica'
    )
    try:
        raw = _search(query)
    except Exception as e:  # noqa: BLE001
        logger.warning("web_lookup.search_failed", razon_social=razon, error=str(e))
        return WebFindings(razon_social=razon, found=False)

    results = raw.get("results") or []
    answer = str(raw.get("answer") or "").strip()
    fuentes = [str(r["url"]) for r in results if r.get("url")][:MAX_FUENTES]
    snippets = [str(r.get("content", "")).strip() for r in results if r.get("content")]

    resumen = answer or " ".join(snippets[:3])
    resumen = _truncate(resumen, MAX_RESUMEN_CHARS)

    # Contenido del sitio para redactar la justificación: primer resultado con
    # texto crudo (Tavily lo devuelve en `raw_content` con include_raw_content).
    sitio_oficial = fuentes[0] if fuentes else None
    contenido_web = ""
    for r in results:
        raw_content = str(r.get("raw_content") or "").strip()
        if raw_content:
            contenido_web = _truncate(raw_content, MAX_CONTENIDO_CHARS)
            sitio_oficial = str(r.get("url") or sitio_oficial)
            break

    found = bool(resumen)
    if not found:
        logger.info("web_lookup.sin_resultados", razon_social=razon)
    return WebFindings(
        razon_social=razon,
        found=found,
        resumen=resumen,
        fuentes=fuentes,
        sitio_oficial=sitio_oficial,
        contenido_web=contenido_web,
    )


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _default_search(query: str) -> dict[str, Any]:
    """Búsqueda real contra Tavily; el cliente se construye perezosamente."""
    from tavily import TavilyClient

    settings = get_settings()
    client = TavilyClient(api_key=settings.tavily_api_key)
    return client.search(
        query=query,
        max_results=MAX_FUENTES,
        include_answer=True,
        include_raw_content=True,  # trae el texto del sitio para la justificación
        search_depth="basic",
    )
