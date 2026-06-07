"""Tests del módulo catálogo + code_resolver.

El `loader` se prueba contra el Anexo real (`config/catalogo_destinos.xlsx`).
El `code_resolver` se prueba con un LLM fake inyectado: no toca red ni API key.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from agropecuario.catalogo.code_resolver import CodeResolver, ResolverResult
from agropecuario.catalogo.loader import Catalogo, CatalogoEntry, load_catalogo

# --- loader ---------------------------------------------------------------

def test_load_catalogo_real():
    cat = load_catalogo()
    # El Anexo trae cientos de destinos repartidos en varias categorías macro.
    assert len(cat) > 200
    assert len(cat.categorias) >= 5
    # Las categorías reales empiezan con un número de sección.
    assert any(c.startswith("1.") for c in cat.categorias)


def test_load_catalogo_descarta_pies_de_pagina():
    cat = load_catalogo()
    # Ninguna nota de pie ("Nota:", "*Se debe", "Fecha Actualización") debe
    # haber entrado como categoría macro.
    for c in cat.categorias:
        assert not c.startswith("Nota")
        assert not c.startswith("*")
        assert "Actualización" not in c


def test_catalogo_arrastra_categoria():
    cat = load_catalogo()
    # Café (141100) está en "1. Actividades de Producción", varias filas debajo
    # del encabezado del bloque: prueba que la categoría se arrastró.
    cafe = cat.by_cod_destino(141100)
    assert cafe is not None
    assert cafe.categoria_macro.startswith("1.")


def test_by_categoria_subdivide():
    cat = load_catalogo()
    primera = cat.categorias[0]
    subset = cat.by_categoria(primera)
    assert 0 < len(subset) < len(cat)
    assert all(e.categoria_macro == primera for e in subset)


# --- code_resolver --------------------------------------------------------

def _fake_catalogo() -> Catalogo:
    return Catalogo(
        entries=[
            CatalogoEntry(
                categoria_macro="1. Actividades de Producción",
                cod_destino=141100,
                destino="Café",
                producto_relacionado="141100 Café",
                plazo_dias=180,
                linea_credito="Inversión",
            ),
            CatalogoEntry(
                categoria_macro="1. Actividades de Producción",
                cod_destino=237280,
                destino="Ganadería de ceba",
                producto_relacionado="237280 Ganadería de ceba",
                plazo_dias=180,
                linea_credito="Capital de trabajo",
            ),
            CatalogoEntry(
                categoria_macro="3. Actividades de Comercialización",
                cod_destino=307016,
                destino="Anticipo a productores",
                producto_relacionado="Todos",
                plazo_dias=180,
                linea_credito="Capital de trabajo",
            ),
        ]
    )


def _make_chat(categoria_idx: int, destino_idx: int, confianza: str = "alta"):
    """Fake `chat`: el primer call resuelve categoría, el segundo el destino."""
    calls = {"n": 0}

    def chat(messages: Sequence[BaseMessage], model: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"indice": categoria_idx})
        return json.dumps({"indice": destino_idx, "confianza": confianza})

    return chat


def test_resolver_two_step_happy_path():
    cat = _fake_catalogo()
    # Categoría 0 = Producción; dentro de ella, destino 0 = Café.
    resolver = CodeResolver(catalogo=cat, chat=_make_chat(0, 0))
    result = resolver.resolve("Cultivo de café", destino="Renovación de cafetales")

    assert isinstance(result, ResolverResult)
    assert result.cod_rubro == 141100
    assert result.descripcion_rubro == "Café"
    assert result.linea_credito == "Inversión"
    assert result.cod_linea == 2  # mapeo Inversión → 2
    assert result.categoria_macro.startswith("1.")
    assert result.confianza == "alta"


def test_resolver_mapea_capital_de_trabajo():
    cat = _fake_catalogo()
    # Categoría 0 = Producción; destino 1 = Ganadería de ceba (Capital de trabajo).
    resolver = CodeResolver(catalogo=cat, chat=_make_chat(0, 1))
    result = resolver.resolve("Engorde de novillos")
    assert result.cod_rubro == 237280
    assert result.cod_linea == 1  # Capital de trabajo → 1


def test_resolver_to_actividad_shape():
    """Lo que to_actividad() devuelve debe encajar en la tabla de la sección 5."""
    cat = _fake_catalogo()
    resolver = CodeResolver(catalogo=cat, chat=_make_chat(0, 0))
    sub = resolver.resolve("café").to_actividad()
    assert set(sub) == {"cod_linea", "cod_rubro", "descripcion_rubro"}


def test_resolver_indice_invalido_cae_en_fallback():
    cat = _fake_catalogo()

    def bad_chat(messages: Sequence[BaseMessage], model: str) -> str:
        return json.dumps({"indice": 999})  # fuera de rango en ambos pasos

    resolver = CodeResolver(catalogo=cat, chat=bad_chat)
    result = resolver.resolve("algo raro")
    # No revienta: cae al primer elemento con confianza baja.
    assert result.cod_rubro == 141100
    assert result.confianza == "baja"


def test_resolver_json_invalido_no_revienta():
    cat = _fake_catalogo()

    def junk_chat(messages: Sequence[BaseMessage], model: str) -> str:
        return "esto no es json"

    resolver = CodeResolver(catalogo=cat, chat=junk_chat)
    result = resolver.resolve("café")
    assert result.cod_rubro == 141100  # fallback al primer destino
