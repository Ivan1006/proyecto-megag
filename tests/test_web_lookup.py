"""Tests de la investigación web (lookup Tavily + comparador + cableado).

No tocan red ni API key: la búsqueda web y el LLM se inyectan con stubs
deterministas.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage

from agropecuario.catalogo.code_resolver import CodeResolver
from agropecuario.catalogo.loader import Catalogo, CatalogoEntry
from agropecuario.generacion.enricher import enrich_fields
from agropecuario.investigacion.comparador import MismatchResult, compare_actividades
from agropecuario.investigacion.web_lookup import WebFindings, lookup_company
from agropecuario.storage import db

# --- web_lookup -----------------------------------------------------------


def _fake_tavily(_query: str) -> dict[str, Any]:
    return {
        "answer": "PORCICOLA APA S.A.S. se dedica a la cría y engorde de cerdos.",
        "results": [
            {"url": "https://apa.example/quienes-somos", "content": "cría de cerdos"},
            {"url": "https://directorio.example/apa", "content": "porcicultura"},
        ],
    }


def test_lookup_company_arma_findings_desde_tavily():
    findings = lookup_company("PORCICOLA APA S.A.S.", search=_fake_tavily)
    assert findings.found
    assert "cerdos" in findings.resumen.lower()
    assert findings.fuentes == [
        "https://apa.example/quienes-somos",
        "https://directorio.example/apa",
    ]


def test_lookup_company_sin_razon_no_busca():
    findings = lookup_company("   ", search=_fake_tavily)
    assert not findings.found
    assert findings.fuentes == []


def test_lookup_company_search_falla_degrada():
    def boom(_query: str) -> dict[str, Any]:
        raise RuntimeError("Tavily 500")

    findings = lookup_company("ACME S.A.", search=boom)
    assert not findings.found
    assert findings.razon_social == "ACME S.A."


def test_lookup_company_sin_resultados_found_false():
    findings = lookup_company("ACME S.A.", search=lambda _q: {"answer": "", "results": []})
    assert not findings.found


# --- comparador -----------------------------------------------------------


def _chat_discrepa(_messages: Sequence[BaseMessage], _model: str) -> str:
    return json.dumps({"discrepancia": True, "explicacion": "correo=café, web=software"})


def test_comparador_marca_discrepancia():
    web = WebFindings(razon_social="X", found=True, resumen="desarrollo de software")
    result = compare_actividades("cultivo de café", web, chat=_chat_discrepa)
    assert result.discrepancia
    assert result.actividad_web == "desarrollo de software"


def test_comparador_sin_web_no_compara_ni_llama_llm():
    # Si la web no encontró nada, no hay base → no se invoca el LLM.
    def no_debe_llamarse(_m: Sequence[BaseMessage], _model: str) -> str:
        raise AssertionError("no debería invocar el LLM sin base de comparación")

    web = WebFindings(razon_social="X", found=False)
    result = compare_actividades("cultivo de café", web, chat=no_debe_llamarse)
    assert not result.discrepancia


def test_comparador_sin_actividad_correo_usa_web_como_apoyo():
    web = WebFindings(razon_social="X", found=True, resumen="ganadería")
    result = compare_actividades("", web, chat=_chat_discrepa)
    assert not result.discrepancia
    assert result.actividad_web == "ganadería"


# --- cableado en code_resolver + enricher ---------------------------------


def _fake_catalogo() -> Catalogo:
    return Catalogo(
        entries=[
            CatalogoEntry(
                categoria_macro="1. Producción",
                cod_destino=141100,
                destino="Café",
                linea_credito="Inversión",
            )
        ]
    )


class _StubNoManual:
    available = False

    def contexto(self, query: str, k: int = 5) -> str:  # pragma: no cover - no se usa
        return ""


def test_code_resolver_inyecta_contexto_web_en_paso2():
    capturado: dict[str, str] = {}

    def chat(messages: Sequence[BaseMessage], model: str) -> str:
        capturado["last"] = str(messages[-1].content)
        return json.dumps({"indice": 0, "confianza": "media"})

    resolver = CodeResolver(
        catalogo=_fake_catalogo(), chat=chat, retriever=_StubNoManual()
    )
    resolver.resolve("café", contexto_web="La empresa se dedica a la porcicultura")

    assert "porcicultura" in capturado["last"]
    assert "correo SIEMPRE manda" in capturado["last"]


def test_enricher_propaga_contexto_web_al_resolver():
    seen: dict[str, Any] = {}

    class FakeResolver:
        def resolve(self, actividad, destino=None, contexto_web=None):
            seen["contexto_web"] = contexto_web
            from agropecuario.catalogo.code_resolver import ResolverResult

            return ResolverResult(cod_rubro=141100, descripcion_rubro="Café", categoria_macro="c")

    enrich_fields(
        {"actividades": [{"actividad": "café"}]},
        resolver=FakeResolver(),
        defaults={},
        contexto_web="web ctx",
    )
    assert seen["contexto_web"] == "web ctx"


# --- migración de DB ------------------------------------------------------


def test_ensure_columns_migra_db_vieja(tmp_path):
    db_path = tmp_path / "old.sqlite"
    with db.connection(db_path) as conn:
        conn.execute(
            "CREATE TABLE runs (id INTEGER PRIMARY KEY, thread_id TEXT, "
            "last_message_id TEXT, status TEXT, started_at TEXT)"
        )

    db.init_db(db_path)  # aplica ensure_columns

    with db.connection(db_path) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}
    assert {"discrepancia_correo_web", "web_actividad_resumen", "web_fuentes_json"} <= cols


# --- cableado en runner ---------------------------------------------------


def test_investigar_web_guarda_flag_y_devuelve_contexto(monkeypatch):
    from agropecuario import runner
    from agropecuario.investigacion import comparador, web_lookup

    monkeypatch.setattr(
        web_lookup,
        "lookup_company",
        lambda rz: WebFindings(
            razon_social=rz, found=True, resumen="cría de cerdos", fuentes=["http://x"]
        ),
    )
    monkeypatch.setattr(
        comparador,
        "compare_actividades",
        lambda correo, web: MismatchResult(
            discrepancia=True, actividad_correo=correo, actividad_web=web.resumen
        ),
    )

    class _S:
        web_lookup_enabled = True
        tavily_api_key = "k"

    monkeypatch.setattr(runner, "get_settings", lambda: _S())

    captured: dict[str, Any] = {}
    monkeypatch.setattr(runner.db, "update_run", lambda run_id, **kw: captured.update(kw))

    fields = {
        "beneficiario_razon_social": "PORCICOLA APA S.A.S.",
        "actividades": [{"actividad": "porcicultura"}],
    }
    ctx = runner._investigar_web(1, fields)

    assert ctx == "cría de cerdos"
    assert captured["discrepancia_correo_web"] is True
    assert captured["web_actividad_resumen"] == "cría de cerdos"
    assert captured["web_fuentes_json"] == ["http://x"]


def test_investigar_web_desactivado_sin_llave(monkeypatch):
    from agropecuario import runner

    class _S:
        web_lookup_enabled = True
        tavily_api_key = ""  # sin llave → degrada

    monkeypatch.setattr(runner, "get_settings", lambda: _S())
    assert runner._investigar_web(1, {"beneficiario_razon_social": "X"}) is None
