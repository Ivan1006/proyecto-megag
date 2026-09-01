"""Clasificación del tamaño del productor — Manual Finagro, numeral 7.1.

El formulario exige marcar si el beneficiario es pequeño, mediano o gran
productor. El Manual de Servicios (pp. 16-18) define esa clasificación de forma
**completamente determinística** a partir de dos cifras de los estados
financieros: los **ingresos brutos anuales** y los **activos totales**. No hay
nada que un LLM deba adivinar aquí, así que no interviene ninguno.

Los umbrales del manual están en **UVB** (Unidad de Valor Básico), mientras que
el correo trae pesos: la conversión y los cortes viven en
`config/tamano_productor.yaml` — incluido el valor del UVB, que se ajusta cada
año por el IPC sin alimentos.

Cuatro segmentos, evaluados de mayor a menor (mediano y gran productor se
cumplen con **cualquiera** de sus dos condiciones, así que bajar en cascada es la
forma más simple de cubrir todos los casos sin huecos):

    ingresos > 288.402 UVB ......................... gran productor
    activos  > 530.150 UVB ......................... gran productor
    ingresos >  14.844 UVB ......................... mediano productor
    activos  >  47.714 UVB ......................... mediano productor
    ingresos >   5.302 UVB ......................... pequeño productor
    resto .......................... pequeño productor de ingresos bajos

Excepción del manual (p.17): para beneficiarios de Reforma Agraria, programas de
adjudicación o compra de tierras del Gobierno Nacional, **el valor de la tierra
no computa** dentro de los activos totales.

Fuera de alcance: el numeral 7.2 define además "usuarios especiales" (mujer
rural, joven rural, víctima…) que priman sobre la clasificación por tamaño. No se
implementa aquí; ver [[Tareas pendientes]] del vault.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from ..logging_conf import get_logger
from .periodo import Periodo

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "tamano_productor.yaml"


class TamanoProductor(StrEnum):
    """Los cuatro segmentos del numeral 7.1. El valor es el nombre del manual."""

    PEQUENO_INGRESOS_BAJOS = "pequeño productor de ingresos bajos"
    PEQUENO = "pequeño productor"
    MEDIANO = "mediano productor"
    GRANDE = "gran productor"


@dataclass(frozen=True)
class Clasificacion:
    """Resultado con su rastro: qué se comparó y contra qué regla del manual."""

    tamano: TamanoProductor
    ingresos_uvb: float
    activos_uvb: float
    motivo: str  # regla concreta que decidió, para auditar el formulario
    # Periodo del que salieron las cifras (Manual p.15, num. 7a). Se conserva
    # para poder auditar el formulario: una clasificación sobre un periodo sin
    # confirmar no vale lo mismo que una sobre un cierre.
    periodo: Periodo | None = None

    @property
    def marca_formulario(self) -> str:
        """Casilla del Excel: los dos segmentos de pequeño comparten la misma."""
        return _MARCAS[self.tamano]


# Segmento → casilla, cargado de la config al primer uso (ver `load_config`).
_MARCAS: dict[TamanoProductor, str] = {}


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Carga `config/tamano_productor.yaml` y cachea el mapa de marcas."""
    raw = yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))
    for nombre, marca in (raw.get("marca_formulario") or {}).items():
        _MARCAS[TamanoProductor(nombre)] = marca
    return raw


def clasificar(
    ingresos_brutos_anuales: float | None,
    activos_totales: float | None,
    *,
    valor_tierra: float = 0.0,
    es_reforma_agraria: bool = False,
    periodo: Periodo | None = None,
    config: dict[str, Any] | None = None,
) -> Clasificacion | None:
    """Clasifica al productor. Devuelve `None` si faltan datos para decidir.

    Ambas cifras van en **pesos** (como vienen de los estados financieros); la
    conversión a UVB se hace aquí. `None` no es un fallo: significa que el correo
    no traía los estados financieros y la clasificación no se puede calcular —
    quien llama decide qué hacer (el `enricher` respeta lo que dijera el correo).

    `periodo` es el veredicto de `clasificacion.periodo`: si las cifras no salen
    de un periodo cerrado (un acumulado a junio, un cierre más viejo que el
    penúltimo), esto devuelve `None` en vez de clasificar sobre una base
    equivocada — el manual (p.15, num. 7a) exige el último o penúltimo periodo
    cerrado. Sin `periodo` no se aplica esa puerta, para no romper llamadas que
    ya validaron el periodo por su cuenta.

    `config=None` carga `config/tamano_productor.yaml`; se inyecta en los tests.
    """
    if ingresos_brutos_anuales is None or activos_totales is None:
        return None
    if periodo is not None and not periodo.clasifica:
        return None

    cfg = config if config is not None else load_config()
    if not _MARCAS:  # config inyectada en tests: puebla el mapa de marcas igual
        for nombre, marca in (cfg.get("marca_formulario") or {}).items():
            _MARCAS[TamanoProductor(nombre)] = marca

    uvb_cop = float(cfg["uvb_cop"])
    u = cfg["umbrales_uvb"]

    activos = float(activos_totales)
    if es_reforma_agraria and valor_tierra:
        # Manual p.17: la tierra no computa para estos beneficiarios.
        activos = max(0.0, activos - float(valor_tierra))

    ingresos_uvb = float(ingresos_brutos_anuales) / uvb_cop
    activos_uvb = activos / uvb_cop

    def _r(tamano: TamanoProductor, motivo: str) -> Clasificacion:
        return Clasificacion(
            tamano=tamano,
            ingresos_uvb=round(ingresos_uvb, 2),
            activos_uvb=round(activos_uvb, 2),
            motivo=motivo,
            periodo=periodo,
        )

    # De mayor a menor. En cada escalón ya se sabe que los cortes de arriba no se
    # cumplieron, así que las condiciones "cualquiera de las dos" del manual se
    # reducen a una sola comparación por línea.
    if ingresos_uvb > u["ingresos_mediano"]:
        return _r(TamanoProductor.GRANDE, f"ingresos > {u['ingresos_mediano']} UVB")
    if activos_uvb > u["activos_mediano"]:
        return _r(TamanoProductor.GRANDE, f"activos > {u['activos_mediano']} UVB")
    if ingresos_uvb > u["ingresos_pequeno"]:
        return _r(TamanoProductor.MEDIANO, f"ingresos > {u['ingresos_pequeno']} UVB")
    if activos_uvb > u["activos_pequeno"]:
        return _r(TamanoProductor.MEDIANO, f"activos > {u['activos_pequeno']} UVB")
    if ingresos_uvb > u["ingresos_pequeno_bajos"]:
        return _r(TamanoProductor.PEQUENO, f"ingresos > {u['ingresos_pequeno_bajos']} UVB")
    return _r(
        TamanoProductor.PEQUENO_INGRESOS_BAJOS,
        f"ingresos <= {u['ingresos_pequeno_bajos']} UVB y activos <= {u['activos_pequeno']} UVB",
    )
