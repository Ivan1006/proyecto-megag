"""Comparador actividad-del-correo vs. actividad-de-la-web (LLM).

Decide si lo que el correo dice que hace la empresa contradice lo que sugiere la
búsqueda web. El resultado se persiste como flag de discrepancia para el
dashboard. **El correo siempre manda**: este módulo solo señala, no corrige.

- Si la web no encontró nada, o el correo no describe la actividad, NO hay base
  para comparar → `discrepancia=False` (la web se usará solo como apoyo).
- Solo se marca discrepancia cuando ambas fuentes describen actividades
  claramente distintas.

El LLM se inyecta vía `chat` para poder testear sin red ni API key.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from ..logging_conf import get_logger
from ..settings import get_settings
from .web_lookup import WebFindings

logger = get_logger(__name__)

# `chat(messages, model)` -> texto de la respuesta. Inyectable para tests.
ChatFn = Callable[[Sequence[BaseMessage], str], str]

_SYSTEM = (
    "Eres un analista de crédito agropecuario. Comparas la actividad económica "
    "que declara un cliente en su correo con la que sugiere una búsqueda web de "
    "su razón social. Solo marcas discrepancia cuando describen actividades "
    "CLARAMENTE distintas (p. ej. el correo dice ganadería y la web dice software). "
    "Diferencias de redacción o de nivel de detalle NO son discrepancia. Respondes "
    "SIEMPRE con un único JSON válido, sin texto adicional."
)


class MismatchResult(BaseModel):
    """Veredicto de la comparación correo vs. web."""

    discrepancia: bool = False
    actividad_correo: str = ""
    actividad_web: str = ""
    explicacion: str = ""


def compare_actividades(
    correo_actividad: str,
    web: WebFindings,
    chat: ChatFn | None = None,
) -> MismatchResult:
    """Compara la actividad del correo con la de la web vía LLM."""
    correo = (correo_actividad or "").strip()
    # Sin base para comparar: la web se usa solo como apoyo, no como discrepancia.
    if not web.found or not correo:
        return MismatchResult(
            discrepancia=False, actividad_correo=correo, actividad_web=web.resumen
        )

    _chat = chat or _default_chat
    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(
            content=(
                "Compara estas dos descripciones de la actividad de la empresa.\n\n"
                f"Actividad según el CORREO:\n{correo}\n\n"
                f"Actividad según la WEB (razón social «{web.razon_social}»):\n"
                f"{web.resumen}\n\n"
                'Responde JSON: {"discrepancia": <true|false>, '
                '"explicacion": "<motivo breve>"}'
            )
        ),
    ]
    data = _invoke_json(_chat, messages, get_settings().openai_model_mini)
    return MismatchResult(
        discrepancia=bool(data.get("discrepancia", False)),
        actividad_correo=correo,
        actividad_web=web.resumen,
        explicacion=str(data.get("explicacion", "")),
    )


def _invoke_json(
    chat: ChatFn, messages: Sequence[BaseMessage], model: str
) -> dict[str, Any]:
    raw = chat(messages, model)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("comparador.json_invalido", raw=str(raw)[:300])
        return {}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _default_chat(messages: Sequence[BaseMessage], model: str) -> str:
    """Implementación real contra OpenAI; se construye perezosamente."""
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    llm = ChatOpenAI(
        model=model,
        api_key=settings.openai_key,
        temperature=0,
    ).bind(response_format={"type": "json_object"})
    response = llm.invoke(list(messages))
    return response.content if isinstance(response.content, str) else str(response.content)
