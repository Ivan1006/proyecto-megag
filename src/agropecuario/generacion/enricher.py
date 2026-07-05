"""Enriquecedor del formulario Finagro: consolida el dict final para el render.

Toma la salida cruda del `mapper` (campos en lenguaje natural + cifras) y la
deja lista para `excel_writer.render_excel()`:

1. **Defaults** — mezcla `config/defaults.yaml` (intermediario financiero, etc.);
   los datos del correo tienen prioridad sobre los defaults.
2. **Códigos de la sección 5** — por cada fila de `actividades` que no traiga
   código, invoca el sub-agente `code_resolver` con la `actividad`/`destino` en
   lenguaje natural y fusiona `cod_linea`/`cod_rubro`/`descripcion_rubro`. Las
   filas que YA traen `cod_rubro` (p. ej. el demo) se respetan sin llamar al LLM.
3. **Cronograma de inversión** — si faltan, calcula `cronograma_fecha_inicial`
   (primero del mes en curso) y `cronograma_fecha_final` (inicial + el mayor
   `plazo_meses` de las actividades).
4. **Validación de sumas** — avisa (warning) si la suma de `valor_total_credito`
   excede la de `valor_total_proyecto` (regla cruzada `total_credito_consistente`).
   Los totales del Excel los calcula la fórmula `=SUM(...)` del template; aquí no
   se escriben, solo se validan.

El `code_resolver` se inyecta vía `resolver` y la fecha vía `today` para poder
testear sin red ni API key.
"""

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from ..catalogo.code_resolver import CodeResolver
from ..logging_conf import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULTS_PATH = PROJECT_ROOT / "config" / "defaults.yaml"

_DATE_FMT = "%d/%m/%Y"


def enrich_fields(
    fields: dict[str, Any],
    *,
    resolver: CodeResolver | None = None,
    today: date | None = None,
    defaults: dict[str, Any] | None = None,
    contexto_web: str | None = None,
) -> dict[str, Any]:
    """Devuelve una copia consolidada de `fields` lista para `render_excel`.

    No muta el dict de entrada. `defaults=None` carga `config/defaults.yaml`;
    pasa `defaults={}` para omitirlos. `resolver`/`today` son inyectables.
    `contexto_web` es un resumen (opcional) de la actividad de la empresa según
    una búsqueda web; se pasa al `code_resolver` como apoyo (el correo manda).
    """
    if defaults is None:
        defaults = load_defaults()
    merged: dict[str, Any] = {**defaults, **fields}

    actividades = merged.get("actividades") or []
    merged["actividades"] = _resolve_codes(actividades, resolver, contexto_web)

    _ensure_cronograma(merged, today or date.today())

    for detalle in validate_sumas(merged["actividades"]):
        logger.warning("enricher.suma_inconsistente", detalle=detalle)

    return merged


def load_defaults() -> dict[str, Any]:
    """Carga `config/defaults.yaml` (vacío si no existe)."""
    if not DEFAULTS_PATH.exists():
        return {}
    return yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8")) or {}


# --- sección 5: resolución de códigos -------------------------------------

def _resolve_codes(
    actividades: list[dict[str, Any]],
    resolver: CodeResolver | None,
    contexto_web: str | None = None,
) -> list[dict[str, Any]]:
    """Completa los códigos Finagro de cada fila que no los traiga.

    El `CodeResolver` se construye perezosamente (solo si hace falta una
    resolución), para no exigir catálogo/API key cuando todas las filas ya
    tienen `cod_rubro`. Cada fallo se aísla por fila: se registra y la fila
    sigue sin códigos en lugar de tumbar todo el render.
    """
    out: list[dict[str, Any]] = []
    _resolver = resolver
    for raw in actividades:
        act = dict(raw)
        descripcion = act.get("actividad") or act.get("descripcion_rubro")
        if not act.get("cod_rubro") and descripcion:
            if _resolver is None:
                try:
                    _resolver = CodeResolver()
                except Exception as e:  # noqa: BLE001
                    logger.warning("enricher.resolver_init_failed", error=str(e))
                    out.append(act)
                    continue
            try:
                res = _resolver.resolve(
                    str(descripcion), act.get("destino"), contexto_web=contexto_web
                )
                for key, value in res.to_actividad().items():
                    if value is not None:
                        act[key] = value
                logger.info(
                    "enricher.codigo_resuelto",
                    actividad=descripcion,
                    cod_rubro=act.get("cod_rubro"),
                    confianza=res.confianza,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "enricher.resolve_failed", actividad=descripcion, error=str(e)
                )
        out.append(act)
    return out


# --- cronograma de inversión ----------------------------------------------

def _ensure_cronograma(fields: dict[str, Any], today: date) -> None:
    """Rellena fechas del cronograma si faltan (respeta las provistas)."""
    if not fields.get("cronograma_fecha_inicial"):
        fields["cronograma_fecha_inicial"] = today.replace(day=1).strftime(_DATE_FMT)

    if not fields.get("cronograma_fecha_final"):
        plazos = [
            int(a["plazo_meses"])
            for a in fields.get("actividades") or []
            if a.get("plazo_meses")
        ]
        if plazos:
            inicial = _parse_date(fields["cronograma_fecha_inicial"]) or today.replace(day=1)
            final = _add_months(inicial, max(plazos))
            fields["cronograma_fecha_final"] = final.strftime(_DATE_FMT)


def _parse_date(value: Any) -> date | None:
    try:
        d, m, y = (int(x) for x in str(value).split("/"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# --- validación de sumas ---------------------------------------------------

def validate_sumas(actividades: list[dict[str, Any]]) -> list[str]:
    """Avisos de consistencia de las sumas de la tabla de actividades.

    Refleja la regla cruzada `total_credito_consistente` de `rules.yaml`: la
    suma del crédito no debería superar la suma del valor del proyecto. Los
    totales en sí los calcula la fórmula `=SUM(...)` del template.
    """
    warnings: list[str] = []
    proyecto = sum(_num(a.get("valor_total_proyecto")) for a in actividades)
    credito = sum(_num(a.get("valor_total_credito")) for a in actividades)
    if credito > proyecto:
        warnings.append(
            f"suma valor_total_credito ({credito}) > "
            f"suma valor_total_proyecto ({proyecto})"
        )
    return warnings


def _num(value: Any) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
