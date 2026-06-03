"""Validador: aplica el RuleSet sobre un dict de campos extraídos."""

from __future__ import annotations

import re
from typing import Any

from ..models import FieldValidation
from .rule_engine import FieldRule, RuleSet


def validate_fields(fields: dict[str, Any], rules: RuleSet) -> list[FieldValidation]:
    return [_validate_one(rule, fields.get(rule.id)) for rule in rules.campos]


def _validate_one(rule: FieldRule, value: Any) -> FieldValidation:
    if value in (None, "", []):
        return FieldValidation(
            field_id=rule.id,
            present=False,
            severity="error" if rule.required else "warning",
            message=f"Campo {rule.id} ausente",
        )

    # Tipo
    if rule.tipo == "number":
        try:
            value = float(value)
        except (TypeError, ValueError):
            return FieldValidation(
                field_id=rule.id,
                present=True,
                value=value,
                severity="error",
                message=f"{rule.id} debe ser numérico",
            )

    # Patrón regex
    if rule.patron and isinstance(value, str) and not re.match(rule.patron, value):
        return FieldValidation(
            field_id=rule.id,
            present=True,
            value=value,
            severity="error",
            message=f"{rule.id} no cumple el formato esperado",
        )

    # Rango
    if rule.rango and isinstance(value, (int, float)):
        lo, hi = rule.rango.get("min"), rule.rango.get("max")
        if lo is not None and value < lo:
            return FieldValidation(
                field_id=rule.id, present=True, value=value,
                severity="error", message=f"{rule.id} menor al mínimo ({lo})",
            )
        if hi is not None and value > hi:
            return FieldValidation(
                field_id=rule.id, present=True, value=value,
                severity="error", message=f"{rule.id} mayor al máximo ({hi})",
            )

    # Valores permitidos
    if rule.valores_permitidos and value not in rule.valores_permitidos:
        return FieldValidation(
            field_id=rule.id,
            present=True,
            value=value,
            severity="warning",
            message=f"{rule.id} fuera del catálogo",
        )

    return FieldValidation(field_id=rule.id, present=True, value=value, severity="ok")
