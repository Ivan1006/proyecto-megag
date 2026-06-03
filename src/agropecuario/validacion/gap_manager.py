"""Gap manager: construye ValidationResult y redacta mensaje para el remitente."""

from __future__ import annotations

from ..models import FieldValidation, Gap, ValidationResult
from .rule_engine import RuleSet


def build_result(
    validations: list[FieldValidation],
    rules: RuleSet,
) -> ValidationResult:
    gaps = [_to_gap(v, rules) for v in validations if v.severity in ("error", "warning") and v.severity != "ok"]
    gaps = [g for g in gaps if g is not None]

    required_ok = sum(
        1 for v in validations if v.field_id in rules.required_ids and v.severity == "ok"
    )
    total_req = len(rules.required_ids) or 1
    optional_ok = sum(
        1 for v in validations if v.field_id in rules.optional_ids and v.severity == "ok"
    )
    total_opt = len(rules.optional_ids) or 1

    completitud_req = required_ok / total_req
    completitud_opt = optional_ok / total_opt
    aprobado = (
        completitud_req >= rules.umbral_requeridos
        and completitud_opt >= rules.umbral_opcionales
    )

    return ValidationResult(
        campos=validations,
        gaps=gaps,
        completitud_requeridos=completitud_req,
        completitud_opcionales=completitud_opt,
        aprobado=aprobado,
        mensaje_resumen=_summary(gaps, aprobado),
    )


def draft_reply_for_gaps(result: ValidationResult) -> str:
    """Redacta el correo a enviar al remitente solicitando los campos faltantes."""
    if not result.gaps:
        return ""
    lines = [
        "Buen día,",
        "",
        "Para continuar con la formulación del proyecto agropecuario, necesitamos que "
        "nos envíe la siguiente información:",
        "",
    ]
    for g in result.gaps:
        sugerencia = f" ({g.sugerencia})" if g.sugerencia else ""
        lines.append(f"  • {g.descripcion}{sugerencia}")
    lines += ["", "Por favor responda a este mismo hilo de correo. Gracias."]
    return "\n".join(lines)


def _to_gap(v: FieldValidation, rules: RuleSet) -> Gap | None:
    rule = rules.by_id(v.field_id)
    if rule is None or v.severity == "ok":
        return None
    tipo = (
        "faltante" if not v.present
        else "fuera_de_rango" if rule.rango
        else "formato_invalido" if rule.patron
        else "inconsistencia"
    )
    return Gap(
        field_id=v.field_id,
        descripcion=rule.descripcion or v.field_id,
        tipo=tipo,
        sugerencia=v.message,
    )


def _summary(gaps: list[Gap], aprobado: bool) -> str:
    if aprobado:
        return "Validación superada."
    faltantes = sum(1 for g in gaps if g.tipo == "faltante")
    return f"Validación no superada: {faltantes} campos faltantes, {len(gaps)} observaciones."
