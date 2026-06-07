"""Tests del mapper correo → campos Finagro.

Se inyecta un `chat` fake: ni red ni API key. Se valida que el esquema del
prompt cubra los campos de `rules.yaml` (incluido el sub-esquema del array
`actividades`) y que los CÓDIGOS queden fuera del alcance del mapper.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from langchain_core.messages import BaseMessage

from agropecuario.generacion.mapper import _build_schema_description, map_content_to_fields
from agropecuario.validacion.rule_engine import load_rules

RULES_PATH = Path(__file__).parent.parent / "config" / "rules.yaml"


def _rules():
    return load_rules(RULES_PATH)


def _capturing_chat(reply: str):
    """Fake `chat` que guarda los mensajes recibidos y devuelve `reply`."""
    captured: dict[str, object] = {}

    def chat(messages: Sequence[BaseMessage], model: str) -> str:
        captured["messages"] = list(messages)
        captured["model"] = model
        captured["prompt"] = "\n".join(str(m.content) for m in messages)
        return reply

    return chat, captured


# --- esquema del prompt ---------------------------------------------------


def test_schema_incluye_campos_planos():
    schema = _build_schema_description(_rules())
    assert "beneficiario_razon_social" in schema
    assert "tenencia" in schema
    assert "garantia_fag" in schema


def test_schema_describe_subcampos_de_actividades():
    schema = _build_schema_description(_rules())
    # El array actividades debe explicitar su sub-esquema por elemento.
    assert "actividades" in schema
    assert "Cada elemento es un objeto" in schema
    for sub in ("actividad", "destino", "unidades_hectareas", "valor_total_credito"):
        assert sub in schema


def test_schema_no_pide_codigos_en_actividades():
    """Los códigos los resuelve el code_resolver, no el mapper."""
    schema = _build_schema_description(_rules())
    assert "cod_rubro" not in schema
    assert "cod_linea" not in schema
    assert "descripcion_rubro" not in schema


# --- map_content_to_fields ------------------------------------------------


def test_map_devuelve_dict_parseado():
    payload = {
        "beneficiario_razon_social": "María Gómez",
        "tenencia": "propia",
        "actividades": [
            {
                "actividad": "cultivo de café",
                "destino": "renovación de cafetales",
                "unidades_hectareas": 5,
                "valor_total_credito": 30000,
            }
        ],
    }
    chat, captured = _capturing_chat(json.dumps(payload))
    result = map_content_to_fields("correo de prueba", _rules(), chat=chat)

    assert result == payload
    # Usa el modelo grande por defecto y mete el contenido del correo en el prompt.
    assert "correo de prueba" in captured["prompt"]
    assert "Finagro" in captured["prompt"]


def test_map_json_invalido_devuelve_vacio():
    chat, _ = _capturing_chat("esto no es json")
    result = map_content_to_fields("x", _rules(), chat=chat)
    assert result == {}


def test_map_json_no_objeto_devuelve_vacio():
    chat, _ = _capturing_chat(json.dumps([1, 2, 3]))
    result = map_content_to_fields("x", _rules(), chat=chat)
    assert result == {}
