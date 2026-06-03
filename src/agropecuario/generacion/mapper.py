"""Mapeador correo → campos de la plantilla usando OpenAI.

El LLM recibe el texto combinado (cuerpo + adjuntos) y devuelve JSON con los
campos requeridos/opcionales. La estructura exacta se define desde `rules.yaml`
para evitar acoplar el prompt al código.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..logging_conf import get_logger
from ..settings import get_settings
from ..validacion.rule_engine import RuleSet

logger = get_logger(__name__)

SYSTEM_PROMPT = """Eres un asistente que extrae datos estructurados de correos y
adjuntos para armar proyectos agropecuarios. Devuelve SIEMPRE un JSON válido sin
texto adicional. Si un campo no aparece, déjalo como null."""


def _build_schema_description(rules: RuleSet) -> str:
    lines = ["Campos a extraer:"]
    for c in rules.campos:
        required = "REQUERIDO" if c.required else "opcional"
        extra = []
        if c.alias:
            extra.append(f"alias: {', '.join(c.alias)}")
        if c.valores_permitidos:
            extra.append(f"valores: {c.valores_permitidos}")
        if c.rango:
            extra.append(f"rango: {c.rango}")
        suffix = f" ({'; '.join(extra)})" if extra else ""
        lines.append(f"- {c.id} [{c.tipo}, {required}]: {c.descripcion}{suffix}")
    return "\n".join(lines)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def map_content_to_fields(combined_text: str, rules: RuleSet) -> dict[str, Any]:
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).bind(response_format={"type": "json_object"})

    schema = _build_schema_description(rules)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"{schema}\n\n"
                f"Contenido del correo y adjuntos:\n---\n{combined_text}\n---\n\n"
                f"Devuelve un JSON con una clave por cada campo. Usa null si no está."
            )
        ),
    ]
    response = llm.invoke(messages)
    content = response.content if isinstance(response.content, str) else str(response.content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("mapper.json_invalid", raw=content[:500])
        return {}
