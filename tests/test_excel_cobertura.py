"""Cobertura del template: qué sabe pintar el formulario y qué se queda fuera.

El template del repo es el formulario **viejo**. El vigente tiene campos que este
no: casilla propia para cada segmento de productor, ingresos brutos, LEC, flujo
de caja del productor primario, más detalle de garantía FAG…

La estrategia es que la **extracción vaya por delante del papel**: `rules.yaml` se
guía por el Manual (que sí está vigente) y el mapa de celdas es un adaptador que
se reemplaza cuando llegue el formulario nuevo. Estos tests fijan las dos
propiedades que sostienen esa estrategia:

1. Extraer un campo que el template no recoge **no rompe el render** y queda
   inventariado.
2. Los grupos de marcas viven en el YAML, así que añadir la casilla que falta es
   configuración, no código.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from agropecuario.generacion.excel_writer import (
    CELL_MAP_PATH,
    campos_cubiertos,
    campos_sin_celda,
    render_excel,
)

PROJECT_ROOT = Path(__file__).parent.parent


def _cell_map() -> dict:
    return yaml.safe_load(CELL_MAP_PATH.read_text(encoding="utf-8"))


def test_campos_sin_celda_reporta_lo_que_el_template_no_recoge():
    """Es la lista que habrá que mapear cuando llegue el formulario vigente."""
    fields = {
        "beneficiario_razon_social": "Prueba SAS",       # sí tiene celda
        "beneficiario_ingresos_brutos_anuales": 1_000,   # no la tiene
        "campo_inventado": "x",                          # no la tiene
        "otro_vacio": None,                              # sin valor: no se lista
    }
    huerfanos = campos_sin_celda(fields, _cell_map())
    assert "beneficiario_ingresos_brutos_anuales" in huerfanos
    assert "campo_inventado" in huerfanos
    assert "beneficiario_razon_social" not in huerfanos
    assert "otro_vacio" not in huerfanos


def test_un_campo_sin_celda_no_rompe_el_render(tmp_path):
    """La propiedad que permite extraer más de lo que el papel sabe mostrar."""
    salida = render_excel(
        {
            "beneficiario_razon_social": "Prueba SAS",
            "beneficiario_ingresos_brutos_anuales": 1_234_567_890,
        },
        tmp_path / "salida.xlsx",
    )
    assert salida.exists()


def test_los_campos_del_demo_estan_cubiertos_por_el_template():
    """Regresión: lo que el demo llena hoy debe seguir teniendo dónde pintarse."""
    demo = json.loads(
        (PROJECT_ROOT / "data" / "samples" / "credito_demo.json").read_text(encoding="utf-8")
    )
    assert campos_sin_celda(demo, _cell_map()) == []


def test_las_marcas_viven_en_el_yaml_no_en_python():
    """Añadir la 4ª casilla del template nuevo debe ser config, no código."""
    marcas = _cell_map()["marcas"]
    assert "tipo_beneficiario" in marcas
    assert "tenencia" in marcas


def test_los_cuatro_segmentos_caen_en_las_tres_casillas_de_este_template():
    """Limitación conocida del formulario viejo, explícita y verificada."""
    tb = _cell_map()["marcas"]["tipo_beneficiario"]
    assert tb["pequeño productor de ingresos bajos"] == tb["pequeño productor"]
    assert len(set(tb.values())) == 3


def test_el_mapa_declara_a_qué_template_pertenece():
    """El adaptador dice qué formulario describe: sin eso, cambiarlo es a ciegas."""
    meta = _cell_map()["template"]
    assert meta["archivo"].endswith(".xlsx")
    assert "desactualizado" in meta["estado"]


def test_los_campos_cubiertos_incluyen_los_bloques_no_triviales():
    """El espejo de las funciones `_write_*` no debe olvidar bloques enteros."""
    cubiertos = campos_cubiertos(_cell_map())
    for campo in (
        "actividades",                    # tabla de la sección 5
        "beneficiario_id_numero",         # identificación por filas
        "justificacion_tecnica",          # bloque de texto
        "garantia_fag",                   # marca con lógica propia
        "actividad_economica_codigo",     # campo por dígito
        "tipo_beneficiario",              # grupo de marcas
    ):
        assert campo in cubiertos, f"{campo} quedaría reportado como huérfano"
