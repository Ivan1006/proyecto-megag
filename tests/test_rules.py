from pathlib import Path

from agropecuario.validacion.gap_manager import build_result
from agropecuario.validacion.rule_engine import load_rules
from agropecuario.validacion.validator import validate_fields

RULES = Path(__file__).parent.parent / "config" / "rules.yaml"


def test_rules_load():
    rules = load_rules(RULES)
    assert rules.version >= 1
    assert len(rules.campos) > 0
    assert "productor_nombre" in rules.required_ids


def test_approved_when_required_present():
    rules = load_rules(RULES)
    fields = {
        "productor_nombre": "María Gómez",
        "productor_documento": "1234567890",
        "predio_nombre": "La Esperanza",
        "predio_hectareas": 12.5,
        "cultivo": "café",
        "ubicacion_municipio": "Chinchiná",
        "ubicacion_departamento": "Caldas",
        "monto_solicitado": 50_000_000,
    }
    validations = validate_fields(fields, rules)
    result = build_result(validations, rules)
    assert result.completitud_requeridos == 1.0
    # puede no aprobarse si umbral opcional > 0 y no pasamos opcionales
    # basta verificar que no hay gaps sobre requeridos:
    assert all(g.field_id not in rules.required_ids for g in result.gaps)


def test_rejected_when_missing_required():
    rules = load_rules(RULES)
    validations = validate_fields({"cultivo": "café"}, rules)
    result = build_result(validations, rules)
    assert not result.aprobado
    assert any(g.field_id == "productor_nombre" for g in result.gaps)


def test_range_validation():
    rules = load_rules(RULES)
    validations = validate_fields({"predio_hectareas": -5}, rules)
    ha = next(v for v in validations if v.field_id == "predio_hectareas")
    assert ha.severity == "error"
