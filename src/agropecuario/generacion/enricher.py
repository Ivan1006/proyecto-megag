"""Enriquecedor: cálculos deterministas + secciones narrativas con LLM."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..logging_conf import get_logger
from ..models import CalculatedField
from ..settings import get_settings
from .template_engine import CalculatedSpec, Section, Template

logger = get_logger(__name__)


def compute_calculated(fields: dict[str, Any], template: Template) -> list[CalculatedField]:
    results: list[CalculatedField] = []
    for spec in template.calculados:
        try:
            value = _evaluate(spec, fields)
            results.append(CalculatedField(field_id=spec.id, valor=value, formula=spec.formula))
        except Exception as e:  # noqa: BLE001
            logger.warning("enricher.calc_failed", field=spec.id, error=str(e))
    return results


def _evaluate(spec: CalculatedSpec, fields: dict[str, Any]) -> Any:
    if spec.id == "monto_por_hectarea":
        return round(float(fields["monto_solicitado"]) / float(fields["predio_hectareas"]), 2)
    if spec.id == "cronograma_desembolsos":
        return _cronograma_default(float(fields["monto_solicitado"]))
    # Fallback: evaluar fórmula en un contexto restringido
    if spec.formula:
        safe_ctx = {k: v for k, v in fields.items() if isinstance(v, (int, float))}
        return eval(spec.formula, {"__builtins__": {}}, safe_ctx)  # noqa: S307
    return None


def _cronograma_default(monto: float, cuotas: int = 4) -> list[dict[str, Any]]:
    cuota = round(monto / cuotas, 2)
    return [
        {"cuota": i + 1, "descripcion": f"Desembolso {i + 1}", "monto": cuota}
        for i in range(cuotas)
    ]


def generate_llm_sections(fields: dict[str, Any], template: Template) -> dict[str, str]:
    """Genera texto libre para las secciones marcadas `generado_por_llm: true`."""
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0.3,
    )

    output: dict[str, str] = {}
    for section in template.secciones:
        if not section.generado_por_llm or not section.prompt:
            continue
        output[section.id] = _generate_section(llm, section, fields)
    return output


def _generate_section(llm: ChatOpenAI, section: Section, fields: dict[str, Any]) -> str:
    context = "\n".join(f"- {k}: {v}" for k, v in fields.items())
    messages = [
        SystemMessage(
            content="Eres un analista agropecuario. Responde en español, profesional y conciso."
        ),
        HumanMessage(
            content=f"Datos del proyecto:\n{context}\n\nInstrucción:\n{section.prompt}"
        ),
    ]
    response = llm.invoke(messages)
    return response.content if isinstance(response.content, str) else str(response.content)
