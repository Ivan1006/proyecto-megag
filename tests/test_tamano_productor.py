"""Tests de la clasificación del tamaño del productor (Manual Finagro 7.1).

Es un cálculo determinístico: no hay LLM que inyectar. Los casos van expresados
en UVB y se convierten a pesos con el UVB de prueba, para que se lean contra el
manual sin hacer aritmética mental.
"""

from __future__ import annotations

import pytest

from agropecuario.clasificacion.tamano_productor import (
    TamanoProductor,
    clasificar,
    load_config,
)

UVB = 10_000.0  # valor redondo de prueba: 1 UVB = $10.000

CONFIG = {
    "uvb_cop": UVB,
    "umbrales_uvb": {
        "ingresos_pequeno_bajos": 5_302,
        "ingresos_pequeno": 14_844,
        "ingresos_mediano": 288_402,
        "activos_pequeno": 47_714,
        "activos_mediano": 530_150,
    },
    "marca_formulario": {
        "pequeño productor de ingresos bajos": "pequeño",
        "pequeño productor": "pequeño",
        "mediano productor": "mediano",
        "gran productor": "grande",
    },
}


def _clasificar(ingresos_uvb: float, activos_uvb: float, **kw):
    """Helper: recibe UVB (como el manual) y pasa pesos (como el correo)."""
    return clasificar(ingresos_uvb * UVB, activos_uvb * UVB, config=CONFIG, **kw)


# --- los cuatro segmentos --------------------------------------------------

def test_pequeno_de_ingresos_bajos():
    r = _clasificar(ingresos_uvb=5_000, activos_uvb=40_000)
    assert r.tamano is TamanoProductor.PEQUENO_INGRESOS_BAJOS


def test_pequeno_productor():
    """Ingresos por encima del corte de bajos, activos aún dentro de pequeño."""
    r = _clasificar(ingresos_uvb=10_000, activos_uvb=40_000)
    assert r.tamano is TamanoProductor.PEQUENO


def test_mediano_por_ingresos():
    """Condición I del manual: ingresos entre 14.844 y 288.402 UVB."""
    r = _clasificar(ingresos_uvb=100_000, activos_uvb=40_000)
    assert r.tamano is TamanoProductor.MEDIANO


def test_mediano_por_activos_aunque_los_ingresos_sean_de_pequeno():
    """Condición II: ingresos bajos pero activos > 47.714 UVB → mediano.

    Es el caso que más se presta a error: por ingresos sería pequeño.
    """
    r = _clasificar(ingresos_uvb=1_000, activos_uvb=100_000)
    assert r.tamano is TamanoProductor.MEDIANO


def test_grande_por_ingresos():
    r = _clasificar(ingresos_uvb=300_000, activos_uvb=1_000)
    assert r.tamano is TamanoProductor.GRANDE


def test_grande_por_activos_aunque_los_ingresos_sean_de_mediano():
    """Condición II de gran productor: activos > 530.150 UVB manda."""
    r = _clasificar(ingresos_uvb=100_000, activos_uvb=600_000)
    assert r.tamano is TamanoProductor.GRANDE


# --- bordes exactos (el manual usa "hasta" / "superiores a") ----------------

@pytest.mark.parametrize(
    ("ingresos_uvb", "activos_uvb", "esperado"),
    [
        # El corte es inclusivo: "hasta 5.302" sigue siendo ingresos bajos.
        (5_302, 1_000, TamanoProductor.PEQUENO_INGRESOS_BAJOS),
        (5_303, 1_000, TamanoProductor.PEQUENO),
        # "hasta 14.844" sigue siendo pequeño.
        (14_844, 1_000, TamanoProductor.PEQUENO),
        (14_845, 1_000, TamanoProductor.MEDIANO),
        # "no superen 47.714" de activos: en el borde sigue siendo pequeño.
        (1_000, 47_714, TamanoProductor.PEQUENO_INGRESOS_BAJOS),
        (1_000, 47_715, TamanoProductor.MEDIANO),
        # "inferiores o iguales a 288.402" de ingresos sigue siendo mediano.
        (288_402, 1_000, TamanoProductor.MEDIANO),
        (288_403, 1_000, TamanoProductor.GRANDE),
        # "inferiores o iguales a 530.150" de activos sigue siendo mediano.
        (1_000, 530_150, TamanoProductor.MEDIANO),
        (1_000, 530_151, TamanoProductor.GRANDE),
    ],
)
def test_bordes_de_los_umbrales(ingresos_uvb, activos_uvb, esperado):
    assert _clasificar(ingresos_uvb, activos_uvb).tamano is esperado


# --- excepción de Reforma Agraria (manual p.17) ----------------------------

def test_reforma_agraria_excluye_el_valor_de_la_tierra():
    """Sin la excepción sería mediano por activos; con ella baja a pequeño."""
    sin_excepcion = _clasificar(ingresos_uvb=1_000, activos_uvb=60_000)
    assert sin_excepcion.tamano is TamanoProductor.MEDIANO

    con_excepcion = _clasificar(
        ingresos_uvb=1_000,
        activos_uvb=60_000,
        es_reforma_agraria=True,
        valor_tierra=20_000 * UVB,
    )
    assert con_excepcion.tamano is TamanoProductor.PEQUENO_INGRESOS_BAJOS


def test_valor_tierra_se_ignora_si_no_es_reforma_agraria():
    r = _clasificar(ingresos_uvb=1_000, activos_uvb=60_000, valor_tierra=20_000 * UVB)
    assert r.tamano is TamanoProductor.MEDIANO


# --- datos faltantes -------------------------------------------------------

@pytest.mark.parametrize(
    ("ingresos", "activos"),
    [(None, 1_000.0), (1_000.0, None), (None, None)],
)
def test_sin_datos_no_clasifica(ingresos, activos):
    """Faltan los estados financieros: no se inventa un tamaño, se devuelve None."""
    assert clasificar(ingresos, activos, config=CONFIG) is None


# --- rastro y marca del formulario -----------------------------------------

def test_conserva_las_cifras_en_uvb_para_auditar():
    r = _clasificar(ingresos_uvb=10_000, activos_uvb=40_000)
    assert r.ingresos_uvb == pytest.approx(10_000)
    assert r.activos_uvb == pytest.approx(40_000)
    assert "UVB" in r.motivo


def test_los_dos_segmentos_de_pequeno_comparten_casilla():
    """El formulario solo tiene 3 casillas para los 4 segmentos del manual."""
    bajos = _clasificar(ingresos_uvb=1_000, activos_uvb=1_000)
    pequeno = _clasificar(ingresos_uvb=10_000, activos_uvb=1_000)
    assert bajos.tamano is not pequeno.tamano
    assert bajos.marca_formulario == pequeno.marca_formulario == "pequeño"


# --- la config real del repo -----------------------------------------------

def test_config_real_tiene_los_umbrales_del_manual():
    cfg = load_config()
    u = cfg["umbrales_uvb"]
    assert u["ingresos_pequeno_bajos"] == 5_302
    assert u["ingresos_pequeno"] == 14_844
    assert u["ingresos_mediano"] == 288_402
    assert u["activos_pequeno"] == 47_714
    assert u["activos_mediano"] == 530_150
    assert cfg["uvb_cop"] > 0


def test_config_real_mapea_los_cuatro_segmentos_a_tres_casillas():
    marcas = load_config()["marca_formulario"]
    assert set(marcas) == {t.value for t in TamanoProductor}
    assert set(marcas.values()) == {"pequeño", "mediano", "grande"}
