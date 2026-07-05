"""Tests del match determinístico actividad→código (T5).

El `matcher` se prueba contra el Anexo real (`config/catalogo_destinos.xlsx`);
el `code_resolver` se prueba con LLM fake para verificar las 3 rutas
(determinística / desempate LLM / fallback) sin tocar red ni API key.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from agropecuario.catalogo.code_resolver import CodeResolver
from agropecuario.catalogo.loader import get_catalogo
from agropecuario.catalogo.matcher import (
    _tokens_equivalentes,
    entries_resolubles,
    match_destinos,
)

# Códigos porcinos reales del Anexo (la actividad de PORCICULTORES APA).
PORCINOS = {245100, 235050, 237300, 241160, 104010}
COD_FAG = 410003  # "Comisión Garantía FAG" — el error que T5 debe evitar.
COD_CAFE = 141100  # "Café"


class _StubNoManual:
    """Retriever sin índice: evita embeddings reales en los tests del resolver."""

    available = False

    def contexto(self, query: str, k: int = 5) -> str:  # pragma: no cover
        return ""


# --- normalización / equivalencia de tokens -------------------------------


def test_tokens_equivalentes_raices_compartidas():
    assert _tokens_equivalentes("porcinos", "porcicultura")  # raíz "porci" (5)
    assert _tokens_equivalentes("porcinos", "porcicultores")  # raíz "porci" (5)
    assert _tokens_equivalentes("ganaderia", "ganado")  # raíz "ganad" (5)
    assert _tokens_equivalentes("arroz", "arroz")  # exacto


def test_tokens_no_equivalentes():
    assert not _tokens_equivalentes("cafe", "cacao")
    assert not _tokens_equivalentes("porcinos", "bovinos")
    # Prefijos cortos NO deben igualar (evita 'agro'→'agroforestería', 'ceba'→'cebada').
    assert not _tokens_equivalentes("agro", "agroforesteria")
    assert not _tokens_equivalentes("ceba", "cebada")


# --- matcher contra el catálogo real --------------------------------------


def test_entries_resolubles_excluye_fag_y_seguro():
    resolubles = entries_resolubles(get_catalogo().entries)
    codigos = {e.cod_destino for e in resolubles}
    assert COD_FAG not in codigos  # Comisión Garantía FAG excluida
    assert 191000 not in codigos  # Prima seguro agropecuario excluida


def test_match_porcicultura_encuentra_porcinos():
    resolubles = entries_resolubles(get_catalogo().entries)
    matches = match_destinos("porcicultura PORCICULTORES APA", resolubles)
    codigos = {m.entry.cod_destino for m in matches}
    # Los destinos porcinos aparecen; la Comisión FAG NO (está excluida).
    assert codigos & PORCINOS
    assert COD_FAG not in codigos


def test_match_cafe_cobertura_total():
    resolubles = entries_resolubles(get_catalogo().entries)
    matches = match_destinos("café", resolubles)
    cafe = next((m for m in matches if m.entry.cod_destino == COD_CAFE), None)
    assert cafe is not None
    assert cafe.coverage == 1.0  # el nombre "Café" queda cubierto entero


# --- rutas del code_resolver sobre el catálogo real -----------------------


def test_resolve_deterministico_no_llama_al_llm():
    def chat_prohibido(_m: Sequence[BaseMessage], _model: str) -> str:
        raise AssertionError("no debe invocarse el LLM en un match determinístico")

    resolver = CodeResolver(
        catalogo=get_catalogo(), chat=chat_prohibido, retriever=_StubNoManual()
    )
    result = resolver.resolve("Café")
    assert result.cod_rubro == COD_CAFE
    assert result.metodo == "catalogo"
    assert result.confianza == "alta"


def test_resolve_porcicultura_evita_fag():
    def chat(_m: Sequence[BaseMessage], _model: str) -> str:
        # Elige el primer candidato del shortlist (todos porcinos).
        return json.dumps({"indice": 0, "confianza": "media"})

    resolver = CodeResolver(
        catalogo=get_catalogo(), chat=chat, retriever=_StubNoManual()
    )
    result = resolver.resolve(
        "renovación de crédito cartera sustitutiva",
        beneficiario="PORCICULTORES APA S.A.S.",
    )
    # El caso que motivó T5: ya NO cae en la Comisión FAG.
    assert result.cod_rubro != COD_FAG
    assert "porc" in result.descripcion_rubro.lower()
    assert result.metodo == "llm"
