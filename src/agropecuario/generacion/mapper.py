"""Mapeador correo → campos del formulario Finagro usando OpenAI.

El LLM recibe el texto combinado (cuerpo + adjuntos) y devuelve un JSON con los
campos del formulario Bancolombia/Finagro definidos en `rules.yaml`. La estructura
del esquema se deriva de las reglas para no acoplar el prompt al código.

**Fuera de alcance — códigos**: el mapper extrae solo TEXTO y CIFRAS del correo.
La asignación de códigos Finagro de la sección 5 (`cod_linea`, `cod_rubro`,
`descripcion_rubro`) es responsabilidad del sub-agente `code_resolver`, que parte
de la descripción en lenguaje natural (`actividad`/`destino`) que sí extrae este
mapper. Ver [[Tareas pendientes]] del vault.

El LLM se inyecta vía el parámetro `chat` para poder testear sin red ni API key:
`chat(messages, model) -> str` debe devolver el contenido (idealmente JSON).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from ..logging_conf import get_logger
from ..settings import get_settings
from ..validacion.rule_engine import FieldRule, RuleSet

logger = get_logger(__name__)

# `chat(messages, model)` -> texto de la respuesta. Inyectable para tests.
ChatFn = Callable[[Sequence[BaseMessage], str], str]

SYSTEM_PROMPT = (
    "Eres un analista de crédito agropecuario que extrae datos estructurados de "
    "correos y adjuntos para diligenciar la Solicitud de Crédito Agropecuario "
    "Finagro. Extrae únicamente lo que aparezca en el contenido; no "
    "inventes valores. Para la tabla de actividades (sección 5) extrae la "
    "descripción en lenguaje natural de la actividad y el destino del crédito, "
    "junto con las cifras financieras: NO asignes códigos Finagro (eso lo hace "
    "otro paso). Devuelve SIEMPRE un único JSON válido, sin texto adicional. Si "
    "un campo no aparece, déjalo como null.\n\n"
    "Reglas de extracción (aplícalas solo con datos presentes, sin inventar):\n"
    "- Revisa TODO el contenido, incluidos los adjuntos transcritos; un dato "
    "puede estar en el cuerpo o en un anexo.\n"
    "- Direcciones: si una dirección menciona municipio, departamento o vereda, "
    "sepáralos en sus campos correspondientes (`*_municipio`, `*_departamento`, "
    "`predio_vereda`) además de dejarlos en la dirección.\n"
    "- Tipo de identificación: normaliza a exactamente 'C.C.', 'NIT' o 'C.E.'. "
    "Una razón social de empresa suele usar NIT; una persona natural, C.C. "
    "Deja el campo en null si no puedes determinarlo con el contenido.\n"
    "- garantía FAG: responde 'si' o 'no' según lo que indique el correo.\n"
    "- Números: extrae solo el valor numérico (sin '$', 'COP', '%', separadores "
    "de miles ni unidades) en los campos de tipo number.\n"
    "- Estados financieros: los adjuntos suelen traer un balance o estado de "
    "resultados. De ahí saca `monto_total_activos` (el TOTAL de activos, no un "
    "rubro suelto ni el pasivo o el patrimonio) y "
    "`beneficiario_ingresos_brutos_anuales` (ingresos brutos / operacionales / "
    "ventas del año, antes de costos y deducciones; NO la utilidad). Si las "
    "cifras vienen expresadas en miles o millones, conviértelas a pesos. Si el "
    "balance cubre un periodo distinto de un año, no anualices: deja el campo en "
    "null. Estas dos cifras determinan el tamaño del productor, así que es "
    "preferible dejarlas vacías a arriesgar un valor equivocado.\n"
    "- NO deduzcas `tipo_beneficiario` (pequeño/mediano/grande): lo calcula otro "
    "paso con los umbrales oficiales. Extrae las cifras, no la conclusión."
)


def _describe_field(c: FieldRule, indent: str = "") -> list[str]:
    """Línea(s) de esquema para un campo; recursivo para arrays con item_fields."""
    required = "REQUERIDO" if c.required else "opcional"
    extra = []
    if c.alias:
        extra.append(f"alias: {', '.join(c.alias)}")
    if c.valores_permitidos:
        extra.append(f"valores: {c.valores_permitidos}")
    if c.rango:
        extra.append(f"rango: {c.rango}")
    suffix = f" ({'; '.join(extra)})" if extra else ""
    lines = [f"{indent}- {c.id} [{c.tipo}, {required}]: {c.descripcion}{suffix}"]

    if c.tipo == "array" and c.item_fields:
        lines.append(f"{indent}  Cada elemento es un objeto con estas claves:")
        for sub in c.item_fields:
            lines.extend(_describe_field(sub, indent=indent + "    "))
    return lines


def _build_schema_description(rules: RuleSet) -> str:
    lines = ["Campos a extraer:"]
    for c in rules.campos:
        lines.extend(_describe_field(c))
    return "\n".join(lines)


def map_content_to_fields(
    combined_text: str,
    rules: RuleSet,
    chat: ChatFn | None = None,
) -> dict[str, Any]:
    """Extrae los campos del formulario Finagro del texto combinado del correo."""
    _chat = chat or _default_chat

    schema = _build_schema_description(rules)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"{schema}\n\n"
                f"Contenido del correo y adjuntos:\n---\n{combined_text}\n---\n\n"
                "Devuelve un JSON con una clave por cada campo (usa null si no "
                "está). El campo `actividades` debe ser una lista de objetos con "
                "las claves indicadas en su esquema."
            )
        ),
    ]
    raw = _chat(messages, get_settings().openai_model)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("mapper.json_invalido", raw=str(raw)[:500])
        return {}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _default_chat(messages: Sequence[BaseMessage], model: str) -> str:
    """Implementación real contra OpenAI; se construye perezosamente."""
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    llm = ChatOpenAI(
        model=model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).bind(response_format={"type": "json_object"})
    response = llm.invoke(list(messages))
    return response.content if isinstance(response.content, str) else str(response.content)
