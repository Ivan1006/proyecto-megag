"""Tests del enricher Finagro (consolidación del dict final).

El `code_resolver` se inyecta como stub: no toca red, catálogo ni API key.
Las fechas se inyectan vía `today` para que el cronograma sea determinista.
"""

from __future__ import annotations

from datetime import date

from agropecuario.catalogo.code_resolver import ResolverResult
from agropecuario.generacion.enricher import (
    enrich_fields,
    validate_sumas,
)

FECHA = date(2026, 6, 9)


class _StubResolver:
    """Resolver fake: devuelve códigos fijos y cuenta las llamadas."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, actividad: str, destino: str | None = None) -> ResolverResult:
        self.calls += 1
        return ResolverResult(
            cod_linea=2,
            cod_rubro=141100,
            descripcion_rubro="Café",
            categoria_macro="1. Actividades de Producción",
            confianza="alta",
        )


class _BoomResolver:
    """Resolver que estalla si lo llaman (para verificar que NO se invoca)."""

    def resolve(self, actividad: str, destino: str | None = None) -> ResolverResult:
        raise AssertionError("el resolver no debería invocarse")


# --- resolución de códigos -------------------------------------------------

def test_resuelve_codigos_faltantes():
    stub = _StubResolver()
    fields = {"actividades": [{"actividad": "cultivo de café", "destino": "renovación"}]}
    out = enrich_fields(fields, resolver=stub, today=FECHA, defaults={})
    act = out["actividades"][0]
    assert act["cod_rubro"] == 141100
    assert act["cod_linea"] == 2
    assert act["descripcion_rubro"] == "Café"
    assert stub.calls == 1


def test_respeta_codigos_provistos_sin_llamar_resolver():
    # Fila que ya trae cod_rubro (caso demo / fill-template): no se llama al LLM.
    fields = {
        "actividades": [
            {"descripcion_rubro": "Café", "cod_rubro": 111350, "cod_linea": 2}
        ]
    }
    out = enrich_fields(fields, resolver=_BoomResolver(), today=FECHA, defaults={})
    assert out["actividades"][0]["cod_rubro"] == 111350


def test_resolver_falla_por_fila_no_tumba_render():
    fields = {"actividades": [{"actividad": "algo raro"}]}
    # _BoomResolver lanza; el fallo se aísla y la fila queda sin códigos.
    out = enrich_fields(fields, resolver=_BoomResolver(), today=FECHA, defaults={})
    assert "cod_rubro" not in out["actividades"][0]


# --- cronograma ------------------------------------------------------------

def test_cronograma_calculado_desde_plazo_maximo():
    fields = {
        "actividades": [
            {"cod_rubro": 1, "plazo_meses": 84},
            {"cod_rubro": 2, "plazo_meses": 36},
        ]
    }
    out = enrich_fields(fields, resolver=_BoomResolver(), today=FECHA, defaults={})
    assert out["cronograma_fecha_inicial"] == "01/06/2026"
    # 01/06/2026 + 84 meses (el mayor plazo) = 01/06/2033
    assert out["cronograma_fecha_final"] == "01/06/2033"


def test_cronograma_respeta_fechas_provistas():
    fields = {
        "actividades": [{"cod_rubro": 1, "plazo_meses": 84}],
        "cronograma_fecha_inicial": "15/01/2025",
        "cronograma_fecha_final": "15/01/2030",
    }
    out = enrich_fields(fields, resolver=_BoomResolver(), today=FECHA, defaults={})
    assert out["cronograma_fecha_inicial"] == "15/01/2025"
    assert out["cronograma_fecha_final"] == "15/01/2030"


# --- validación de sumas ---------------------------------------------------

def test_validate_sumas_credito_excede_proyecto():
    actividades = [
        {"valor_total_proyecto": 100, "valor_total_credito": 80},
        {"valor_total_proyecto": 50, "valor_total_credito": 90},
    ]
    warnings = validate_sumas(actividades)
    assert len(warnings) == 1
    assert "valor_total_credito" in warnings[0]


def test_validate_sumas_consistente_sin_avisos():
    actividades = [
        {"valor_total_proyecto": 100, "valor_total_credito": 80},
        {"valor_total_proyecto": 50, "valor_total_credito": 50},
    ]
    assert validate_sumas(actividades) == []


# --- defaults + pureza -----------------------------------------------------

def test_mezcla_defaults_y_correo_tiene_prioridad():
    defaults = {"intermediario_financiero": "BANCOLOMBIA", "oficina": "PRINCIPAL"}
    fields = {"oficina": "MEDELLÍN CENTRO", "actividades": []}
    out = enrich_fields(fields, resolver=_BoomResolver(), today=FECHA, defaults=defaults)
    assert out["intermediario_financiero"] == "BANCOLOMBIA"  # default
    assert out["oficina"] == "MEDELLÍN CENTRO"  # el correo gana


def test_no_muta_el_dict_de_entrada():
    fields = {"actividades": [{"actividad": "café"}]}
    enrich_fields(fields, resolver=_StubResolver(), today=FECHA, defaults={})
    assert fields == {"actividades": [{"actividad": "café"}]}  # intacto
