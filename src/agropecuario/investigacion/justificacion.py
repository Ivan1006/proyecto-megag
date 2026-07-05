"""Redacción de la justificación del crédito (sección B30:S42) vía LLM.

El formulario Finagro pide una justificación técnica/económica del crédito que
hoy no se generaba (salía en blanco). Este módulo la redacta a partir de:

- los datos del correo (razón social, actividad, destino, cifras), y
- (si está disponible) el contenido de la **web** de la empresa, que enriquece
  el texto con a qué se dedica realmente.

Degrada bien: sin web, redacta igual desde los datos del correo. El LLM se
inyecta vía `chat` para testear sin red ni API key.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from ..logging_conf import get_logger
from ..settings import get_settings
from .web_lookup import WebFindings

logger = get_logger(__name__)

# `chat(messages, model)` -> texto de la respuesta. Inyectable para tests.
ChatFn = Callable[[Sequence[BaseMessage], str], str]

MAX_JUSTIFICACION_CHARS = 1500
MAX_WEB_EN_PROMPT = 3000

_SYSTEM = (
    "Eres un analista de crédito agropecuario que redacta la justificación "
    "técnica y económica de una Solicitud de Crédito Agropecuario Finagro. "
    "Escribes un párrafo claro y profesional en español que explique quién es el "
    "beneficiario, a qué se dedica, para qué usará el crédito y por qué es viable. "
    "Usa ÚNICAMENTE la información dada; no inventes cifras, fechas ni datos. Si un "
    "dato no aparece, no lo menciones. Devuelve solo el texto, sin encabezados."
)


def generar_justificacion(
    fields: dict[str, Any],
    web: WebFindings | None = None,
    chat: ChatFn | None = None,
) -> str:
    """Redacta la justificación del crédito. Devuelve "" si no hay datos suficientes."""
    datos = _resumen_datos(fields)
    if not datos.strip():
        return ""

    _chat = chat or _default_chat
    contenido_web = ""
    if web and web.found:
        contenido_web = (web.contenido_web or web.resumen or "")[:MAX_WEB_EN_PROMPT].strip()
    bloque_web = (
        f"Información pública de la empresa (de su sitio web, úsala solo como "
        f"apoyo):\n{contenido_web}\n\n"
        if contenido_web
        else ""
    )

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(
            content=(
                f"Datos de la solicitud:\n{datos}\n\n"
                f"{bloque_web}"
                "Redacta la justificación en 4 a 6 frases, tono formal. Devuelve "
                "SOLO el texto de la justificación."
            )
        ),
    ]
    texto = _chat(messages, get_settings().openai_model).strip()
    return texto[:MAX_JUSTIFICACION_CHARS]


def _resumen_datos(fields: dict[str, Any]) -> str:
    """Arma un bloque compacto con los datos del correo relevantes a la justificación."""
    lineas: list[str] = []

    def add(label: str, value: Any) -> None:
        if value:
            lineas.append(f"- {label}: {value}")

    add("Beneficiario (razón social)", fields.get("beneficiario_razon_social"))
    add("Predio / ubicación", fields.get("predio_nombre_direccion"))

    actividades = fields.get("actividades") or []
    for i, act in enumerate(actividades, 1):
        partes = [
            str(act[k])
            for k in ("actividad", "destino", "descripcion_rubro")
            if act.get(k)
        ]
        campos_cifra = (
            "unidades_hectareas",
            "valor_total_proyecto",
            "valor_total_credito",
            "plazo_meses",
        )
        cifras = [f"{k}={act[k]}" for k in campos_cifra if act.get(k)]
        detalle = " · ".join(dict.fromkeys(partes))
        if detalle or cifras:
            sufijo = f" ({'; '.join(cifras)})" if cifras else ""
            lineas.append(f"- Actividad {i}: {detalle}{sufijo}")

    return "\n".join(lineas)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _default_chat(messages: Sequence[BaseMessage], model: str) -> str:
    """Implementación real contra OpenAI (texto libre, sin JSON forzado)."""
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    llm = ChatOpenAI(model=model, api_key=settings.openai_api_key, temperature=0.2)
    response = llm.invoke(list(messages))
    return response.content if isinstance(response.content, str) else str(response.content)
