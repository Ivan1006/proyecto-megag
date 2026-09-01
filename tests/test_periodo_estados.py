"""Periodo de los estados financieros — Manual Finagro p.15, numeral 7, aspecto a.

El manual exige que los ingresos y los activos con los que se clasifica al
productor salgan del **último o penúltimo periodo CERRADO**. El bug real que
motiva este módulo: llegó un "estado de resultado integral acumulado a 30 de
junio" y el semestre se guardó como si fuera el año, subestimando los ingresos a
la mitad. Cerca de un umbral eso baja un segmento entero.

La regla de diseño es la misma que en T1 y T5: **el LLM extrae hechos** (la fecha
de corte y cuántos meses cubre el estado de resultados) y **el código decide** si
ese periodo sirve.
"""

from __future__ import annotations

from datetime import date

import pytest

from agropecuario.clasificacion.periodo import (
    EstadoPeriodo,
    evaluar_periodo,
    gap_por_periodo,
    periodo_de_campos,
)

HOY = date(2026, 8, 31)


# --- periodo cerrado vs. corte parcial -------------------------------------


def test_cierre_a_31_de_diciembre_es_periodo_cerrado():
    p = evaluar_periodo(date(2025, 12, 31), None, hoy=HOY)
    assert p.estado is EstadoPeriodo.CERRADO
    assert p.clasifica


def test_corte_a_30_de_junio_es_parcial_y_no_clasifica():
    """El caso real del primer run: acumulado a junio tratado como anual."""
    p = evaluar_periodo(date(2026, 6, 30), None, hoy=HOY)
    assert p.estado is EstadoPeriodo.PARCIAL
    assert not p.clasifica
    assert "30/06/2026" in p.motivo


def test_los_meses_cubiertos_mandan_sobre_la_fecha_de_corte():
    """Un ejercicio comercial de 12 meses que no cierra en diciembre sí sirve."""
    p = evaluar_periodo(date(2025, 6, 30), 12, hoy=HOY)
    assert p.estado is EstadoPeriodo.CERRADO


def test_seis_meses_cubiertos_es_parcial_aunque_la_fecha_sea_de_cierre():
    p = evaluar_periodo(date(2025, 12, 31), 6, hoy=HOY)
    assert p.estado is EstadoPeriodo.PARCIAL
    assert "6 meses" in p.motivo


# --- antigüedad: último o penúltimo periodo fiscal -------------------------


def test_el_ultimo_cierre_disponible_es_aceptado():
    assert evaluar_periodo(date(2025, 12, 31), 12, hoy=HOY).estado is EstadoPeriodo.CERRADO


def test_el_penultimo_cierre_tambien_es_aceptado():
    """El manual admite el penúltimo cuando el último aún no está listo."""
    assert evaluar_periodo(date(2024, 12, 31), 12, hoy=HOY).estado is EstadoPeriodo.CERRADO


def test_un_cierre_mas_viejo_que_el_penultimo_no_clasifica():
    p = evaluar_periodo(date(2023, 12, 31), 12, hoy=HOY)
    assert p.estado is EstadoPeriodo.ANTIGUO
    assert not p.clasifica
    assert "2024" in p.motivo  # dice cuál es el mínimo aceptable


def test_en_pleno_31_de_diciembre_ese_mismo_cierre_ya_cuenta():
    p = evaluar_periodo(date(2026, 12, 31), 12, hoy=date(2026, 12, 31))
    assert p.estado is EstadoPeriodo.CERRADO


# --- sin datos: se clasifica, pero avisando --------------------------------


def test_sin_fecha_ni_meses_el_periodo_es_desconocido_pero_deja_clasificar():
    """Decisión del usuario: no bloquear por un balance mal encabezado."""
    p = evaluar_periodo(None, None, hoy=HOY)
    assert p.estado is EstadoPeriodo.DESCONOCIDO
    assert p.clasifica


def test_doce_meses_sin_fecha_de_corte_no_se_puede_juzgar_por_antiguedad():
    p = evaluar_periodo(None, 12, hoy=HOY)
    assert p.estado is EstadoPeriodo.CERRADO


# --- adaptador desde los campos del formulario -----------------------------


def test_periodo_de_campos_arma_la_fecha_con_fecha_balance():
    campos = {"fecha_balance_dia": 31, "fecha_balance_mes": 12, "fecha_balance_anio": 2025}
    p = periodo_de_campos(campos, hoy=HOY)
    assert p.estado is EstadoPeriodo.CERRADO
    assert p.fecha_corte == date(2025, 12, 31)


def test_periodo_de_campos_tolera_una_fecha_incompleta_o_absurda():
    """Un mes 13 o un día suelto no debe tumbar el render: queda desconocido."""
    assert periodo_de_campos({"fecha_balance_dia": 30}, hoy=HOY).estado is EstadoPeriodo.DESCONOCIDO
    campos = {"fecha_balance_dia": 31, "fecha_balance_mes": 13, "fecha_balance_anio": 2025}
    assert periodo_de_campos(campos, hoy=HOY).estado is EstadoPeriodo.DESCONOCIDO


def test_periodo_de_campos_lee_los_meses_cubiertos():
    campos = {
        "fecha_balance_dia": 30,
        "fecha_balance_mes": 6,
        "fecha_balance_anio": 2026,
        "estados_financieros_meses_cubiertos": 6,
    }
    assert periodo_de_campos(campos, hoy=HOY).estado is EstadoPeriodo.PARCIAL


# --- brecha accionable para el dashboard -----------------------------------


def test_sin_cifras_financieras_no_hay_brecha_de_periodo():
    """Si el correo no trae estados financieros, el periodo no es el problema."""
    campos = {"fecha_balance_dia": 30, "fecha_balance_mes": 6, "fecha_balance_anio": 2026}
    assert gap_por_periodo(campos, hoy=HOY) is None


def test_un_corte_parcial_con_cifras_deja_brecha_accionable():
    campos = {
        "beneficiario_ingresos_brutos_anuales": 120_156_226_098,
        "monto_total_activos": 500_000_000,
        "fecha_balance_dia": 30,
        "fecha_balance_mes": 6,
        "fecha_balance_anio": 2026,
    }
    gap = gap_por_periodo(campos, hoy=HOY)
    assert gap is not None
    assert gap.tipo == "inconsistencia"
    assert "último o penúltimo" in (gap.sugerencia or "")


def test_un_periodo_desconocido_deja_brecha_de_aviso_no_de_error():
    campos = {"beneficiario_ingresos_brutos_anuales": 1_000_000_000}
    gap = gap_por_periodo(campos, hoy=HOY)
    assert gap is not None
    assert gap.tipo == "faltante"


def test_un_cierre_valido_no_deja_brecha():
    campos = {
        "beneficiario_ingresos_brutos_anuales": 1_000_000_000,
        "monto_total_activos": 500_000_000,
        "fecha_balance_dia": 31,
        "fecha_balance_mes": 12,
        "fecha_balance_anio": 2025,
    }
    assert gap_por_periodo(campos, hoy=HOY) is None


# --- la calculadora se niega a clasificar sobre un periodo que no sirve ----


def test_clasificar_no_devuelve_nada_si_el_periodo_no_sirve():
    from agropecuario.clasificacion.tamano_productor import clasificar

    parcial = evaluar_periodo(date(2026, 6, 30), 6, hoy=HOY)
    assert clasificar(120_156_226_098, 500_000_000, periodo=parcial) is None


def test_clasificar_sigue_funcionando_con_un_periodo_cerrado():
    from agropecuario.clasificacion.tamano_productor import clasificar

    cerrado = evaluar_periodo(date(2025, 12, 31), 12, hoy=HOY)
    r = clasificar(120_156_226_098, 500_000_000, periodo=cerrado)
    assert r is not None
    assert r.periodo is cerrado


@pytest.mark.parametrize("meses", [0, -3])
def test_meses_cubiertos_absurdos_no_se_toman_como_periodo(meses):
    p = evaluar_periodo(date(2025, 12, 31), meses, hoy=HOY)
    assert p.estado is EstadoPeriodo.CERRADO  # cae de vuelta en la fecha de corte


# --- cableado en el runner -------------------------------------------------


def test_el_runner_persiste_la_brecha_de_periodo_junto_a_las_de_validacion():
    """`save_gaps` reemplaza la lista: la del periodo tiene que ir en el mismo lote."""
    from agropecuario import runner
    from agropecuario.models import Gap, ValidationResult

    result = ValidationResult(
        campos=[],
        gaps=[Gap(field_id="predio_nombre", descripcion="Nombre del predio", tipo="faltante")],
        completitud_requeridos=0.5,
        completitud_opcionales=0.5,
        aprobado=False,
    )
    fields = {
        "beneficiario_ingresos_brutos_anuales": 120_156_226_098,
        "monto_total_activos": 500_000_000,
        "fecha_balance_dia": 30,
        "fecha_balance_mes": 6,
        "fecha_balance_anio": 2026,
    }
    guardadas = runner._gaps_para_persistir(result, fields)
    assert [g["field_id"] for g in guardadas] == ["predio_nombre", "estados_financieros_periodo"]


def test_el_runner_no_inventa_brecha_de_periodo_si_el_cierre_es_valido():
    from agropecuario import runner
    from agropecuario.models import ValidationResult

    result = ValidationResult(
        campos=[], gaps=[], completitud_requeridos=1.0, completitud_opcionales=1.0, aprobado=True
    )
    fields = {
        "beneficiario_ingresos_brutos_anuales": 1_000_000_000,
        "monto_total_activos": 500_000_000,
        "fecha_balance_dia": 31,
        "fecha_balance_mes": 12,
        "fecha_balance_anio": date.today().year - 1,
    }
    assert runner._gaps_para_persistir(result, fields) == []
