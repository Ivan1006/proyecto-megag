"""Tests de validación contra el esquema Finagro v2 de `config/rules.yaml`.

(Antes validaban el esquema v1 — `productor_nombre`, `predio_hectareas` — que
quedó obsoleto al reescribir `rules.yaml` para los campos Bancolombia/Finagro.)
"""

from pathlib import Path

from agropecuario.validacion.gap_manager import build_result
from agropecuario.validacion.rule_engine import load_rules
from agropecuario.validacion.validator import validate_fields

RULES = Path(__file__).parent.parent / "config" / "rules.yaml"

# Conjunto mínimo de campos requeridos v2 con valores válidos (catálogo/rango/patrón).
REQUIRED_OK = {
    "beneficiario_razon_social": "María Gómez Restrepo",
    "beneficiario_id_tipo": "C.C.",
    "beneficiario_id_numero": "43.185.672",
    "beneficiario_direccion": "Vereda El Vergel, Finca La Esperanza",
    "beneficiario_telefono": "3001234567",
    "beneficiario_municipio": "Chinchiná",
    "beneficiario_departamento": "Caldas",
    "tipo_beneficiario": "pequeño",
    "predio_nombre_direccion": "La Esperanza – Vereda El Vergel",
    "predio_extension_has": 12.5,
    "predio_departamento": "Caldas",
    "predio_municipio": "Chinchiná",
    "predio_vereda": "El Vergel",
    "tenencia": "propia",
    "forma_de_llegar": "Desde Chinchiná, vía Palestina, 8 km hasta El Vergel.",
    "justificacion_tecnica": "Renovación de 5 ha de café variedad Castillo.",
    "actividades": [{"actividad": "cultivo de café", "destino": "renovación de cafetales"}],
    "actividad_economica_descripcion": "Cultivo de café",
    "garantia_fag": "si",
}


def test_rules_load():
    rules = load_rules(RULES)
    assert rules.version >= 2
    assert len(rules.campos) > 0
    # Esquema v2: beneficiario_* en lugar del productor_* del v1.
    assert "beneficiario_razon_social" in rules.required_ids
    assert "productor_nombre" not in rules.required_ids


def test_approved_when_required_present():
    rules = load_rules(RULES)
    validations = validate_fields(REQUIRED_OK, rules)
    result = build_result(validations, rules)
    assert result.completitud_requeridos == 1.0
    assert result.aprobado  # umbral opcional = 0.0
    # No debe quedar ninguna brecha sobre campos requeridos.
    assert all(g.field_id not in rules.required_ids for g in result.gaps)


def test_rejected_when_missing_required():
    rules = load_rules(RULES)
    validations = validate_fields({"beneficiario_razon_social": "María Gómez"}, rules)
    result = build_result(validations, rules)
    assert not result.aprobado
    # Un campo requerido ausente debe aparecer como brecha 'faltante'.
    assert any(
        g.field_id == "predio_extension_has" and g.tipo == "faltante"
        for g in result.gaps
    )


def test_range_validation():
    rules = load_rules(RULES)
    # predio_extension_has tiene rango min 0.01: -5 está fuera → error.
    validations = validate_fields({"predio_extension_has": -5}, rules)
    ha = next(v for v in validations if v.field_id == "predio_extension_has")
    assert ha.severity == "error"
