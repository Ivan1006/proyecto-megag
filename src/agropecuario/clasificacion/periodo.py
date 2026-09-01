"""Periodo de los estados financieros — Manual Finagro p.15, numeral 7, aspecto a.

Las dos cifras que clasifican al productor (ingresos brutos y activos totales)
solo valen si vienen de un periodo **cerrado**:

> […] cuyos datos deben corresponder a: el último o penúltimo periodo fiscal, si
> el productor es sujeto fiscal; el último periodo comercial, si no lo es.

Es decir: un cierre, nunca un acumulado parcial ni una proyección. El manual no
contempla anualizar un corte de mitad de año — se buscó explícitamente y no
aparece.

**Por qué existe este módulo**: en el primer run real llegó un "estado de
resultado integral acumulado […] a 30 de junio" y el semestre se guardó en
`beneficiario_ingresos_brutos_anuales`. La regla estaba en el prompt del mapper
("si el periodo no es un año, deja el campo en null") y el LLM no la respetó. El
error de diseño fue pedirle al LLM una DECISIÓN en vez de un HECHO. Aquí se
invierte: el mapper extrae la fecha de corte y los meses cubiertos, y estas
funciones —determinísticas, sin LLM— deciden si ese periodo sirve.

Cuatro estados posibles:

    CERRADO ...... sirve para clasificar
    PARCIAL ...... acumulado a mitad de periodo → NO clasifica
    ANTIGUO ...... cierre anterior al penúltimo periodo fiscal → NO clasifica
    DESCONOCIDO .. no se pudo determinar → clasifica igual, dejando aviso

`DESCONOCIDO` sí clasifica por decisión del usuario (2026-08-31): un balance
anual mal encabezado es más frecuente que uno parcial, y bloquear por falta de
encabezado dejaría casi todos los runs sin clasificar. Queda la brecha para que
un humano lo confirme.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from ..models import Gap

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "tamano_productor.yaml"

# Campos del formulario que traen los hechos del periodo (los llena el mapper).
CAMPO_MESES = "estados_financieros_meses_cubiertos"
CAMPOS_FECHA = ("fecha_balance_dia", "fecha_balance_mes", "fecha_balance_anio")
# Cifras que dependen del periodo: sin ninguna de las dos, el periodo da igual.
CAMPOS_CIFRAS = ("beneficiario_ingresos_brutos_anuales", "monto_total_activos")

# `field_id` sintético de la brecha: no es un campo del formulario, es la
# condición que deben cumplir las cifras. El dashboard lo muestra tal cual.
FIELD_ID_BRECHA = "estados_financieros_periodo"


class EstadoPeriodo(StrEnum):
    CERRADO = "cerrado"
    PARCIAL = "parcial"
    ANTIGUO = "antiguo"
    DESCONOCIDO = "desconocido"


@dataclass(frozen=True)
class Periodo:
    """Veredicto sobre el periodo, con el rastro de por qué."""

    estado: EstadoPeriodo
    motivo: str
    fecha_corte: date | None = None
    meses_cubiertos: int | None = None

    @property
    def clasifica(self) -> bool:
        """Si las cifras de este periodo pueden usarse para clasificar."""
        return self.estado in (EstadoPeriodo.CERRADO, EstadoPeriodo.DESCONOCIDO)

    @property
    def confirmado(self) -> bool:
        """Si además consta que el periodo es cerrado (no solo que no se objeta)."""
        return self.estado is EstadoPeriodo.CERRADO


def _load_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bloque `periodo_estados_financieros` de `config/tamano_productor.yaml`."""
    if config is None:
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return (config or {}).get("periodo_estados_financieros") or {}


def evaluar_periodo(
    fecha_corte: date | None,
    meses_cubiertos: int | None,
    *,
    hoy: date | None = None,
    config: dict[str, Any] | None = None,
) -> Periodo:
    """Decide si un periodo sirve para clasificar. Determinístico, sin LLM.

    `meses_cubiertos` manda sobre `fecha_corte`: un ejercicio comercial de 12
    meses que no cierre en diciembre es igual de válido (el manual habla de
    "periodo comercial" para quien no es sujeto fiscal). La fecha de corte se usa
    cuando no consta la duración, y siempre para juzgar la antigüedad.
    """
    cfg = _load_config(config)
    meses_cerrado = int(cfg.get("meses_periodo_cerrado", 12))
    mes_cierre = int(cfg.get("mes_cierre_fiscal", 12))
    dia_cierre = int(cfg.get("dia_cierre_fiscal", 31))
    periodos = int(cfg.get("periodos_aceptados", 2))
    hoy = hoy or date.today()

    # Un 0 o un negativo es ruido de extracción, no un periodo de 0 meses.
    meses = meses_cubiertos if meses_cubiertos and meses_cubiertos > 0 else None

    if meses is not None:
        if meses < meses_cerrado:
            return Periodo(
                EstadoPeriodo.PARCIAL,
                f"los estados financieros cubren {meses} meses, no un periodo "
                f"cerrado de {meses_cerrado}",
                fecha_corte,
                meses,
            )
    elif fecha_corte is not None:
        if (fecha_corte.month, fecha_corte.day) != (mes_cierre, dia_cierre):
            return Periodo(
                EstadoPeriodo.PARCIAL,
                f"la fecha de corte es {fecha_corte.strftime('%d/%m/%Y')} y no "
                f"consta que cubra 12 meses: parece un acumulado parcial, no un cierre",
                fecha_corte,
                None,
            )
    else:
        return Periodo(
            EstadoPeriodo.DESCONOCIDO,
            "no consta la fecha de corte ni el periodo que cubren los estados financieros",
            None,
            None,
        )

    # Periodo cerrado: falta ver que sea el último o el penúltimo.
    if fecha_corte is None:
        return Periodo(
            EstadoPeriodo.CERRADO,
            f"cubre {meses} meses (sin fecha de corte: no se verifica la antigüedad)",
            None,
            meses,
        )

    ultimo = _ultimo_cierre(hoy, mes_cierre, dia_cierre)
    minimo = ultimo - (periodos - 1)
    if fecha_corte.year < minimo:
        return Periodo(
            EstadoPeriodo.ANTIGUO,
            f"el cierre es de {fecha_corte.year}; el manual exige el último "
            f"({ultimo}) o el penúltimo ({minimo}) periodo",
            fecha_corte,
            meses,
        )
    return Periodo(
        EstadoPeriodo.CERRADO,
        f"cierre de {fecha_corte.year} ({fecha_corte.strftime('%d/%m/%Y')})",
        fecha_corte,
        meses,
    )


def _ultimo_cierre(hoy: date, mes_cierre: int, dia_cierre: int) -> int:
    """Año del último periodo que ya cerró a día de hoy."""
    return hoy.year if (hoy.month, hoy.day) >= (mes_cierre, dia_cierre) else hoy.year - 1


def periodo_de_campos(
    fields: dict[str, Any],
    *,
    hoy: date | None = None,
    config: dict[str, Any] | None = None,
) -> Periodo:
    """`evaluar_periodo` sobre los campos del formulario tal como los deja el mapper."""
    return evaluar_periodo(
        _fecha_balance(fields),
        _entero(fields.get(CAMPO_MESES)),
        hoy=hoy,
        config=config,
    )


def gap_por_periodo(
    fields: dict[str, Any],
    *,
    hoy: date | None = None,
    config: dict[str, Any] | None = None,
) -> Gap | None:
    """Brecha para el dashboard cuando el periodo impide (o no confirma) clasificar.

    Devuelve `None` si el periodo es un cierre válido o si el correo no trajo
    ninguna cifra financiera: sin cifras que clasificar, el periodo no es un
    problema que reportarle al remitente.
    """
    if not any(fields.get(c) not in (None, "") for c in CAMPOS_CIFRAS):
        return None

    periodo = periodo_de_campos(fields, hoy=hoy, config=config)
    if periodo.confirmado:
        return None

    pedido = (
        "envíe los estados financieros del último o penúltimo periodo cerrado "
        "(el manual no admite acumulados parciales ni proyecciones)"
    )
    if periodo.estado is EstadoPeriodo.DESCONOCIDO:
        return Gap(
            field_id=FIELD_ID_BRECHA,
            descripcion="Periodo de los estados financieros sin confirmar",
            tipo="faltante",
            sugerencia=(
                f"{periodo.motivo}; se clasificó el tamaño del productor asumiendo "
                f"que son de un cierre anual — confírmelo o {pedido}"
            ),
        )
    return Gap(
        field_id=FIELD_ID_BRECHA,
        descripcion="Los estados financieros no son de un periodo cerrado",
        tipo="inconsistencia",
        sugerencia=(f"{periodo.motivo}; no se clasificó el tamaño del productor: {pedido}"),
    )


def _fecha_balance(fields: dict[str, Any]) -> date | None:
    """Arma la fecha de corte con `fecha_balance_*`; `None` si falta o es absurda."""
    partes = [_entero(fields.get(c)) for c in CAMPOS_FECHA]
    if any(p is None for p in partes):
        return None
    dia, mes, anio = partes
    try:
        return date(int(anio), int(mes), int(dia))  # type: ignore[arg-type]
    except ValueError:
        return None


def _entero(valor: Any) -> int | None:
    """Los números pueden llegar como int, float o string desde el LLM."""
    if valor in (None, ""):
        return None
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None
