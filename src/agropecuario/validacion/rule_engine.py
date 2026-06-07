"""Carga y compilación de reglas desde rules.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FieldRule:
    id: str
    descripcion: str
    tipo: str
    required: bool
    alias: list[str] = field(default_factory=list)
    patron: str | None = None
    rango: dict[str, float] | None = None
    valores_permitidos: list[Any] | None = None
    # Para campos `tipo: array`: sub-esquema de cada elemento de la lista.
    item_fields: list[FieldRule] = field(default_factory=list)


@dataclass
class CrossRule:
    id: str
    descripcion: str
    expresion: str | None
    severidad: str
    tipo: str | None = None
    tabla: str | None = None


@dataclass
class RuleSet:
    version: int
    campos: list[FieldRule]
    cruzadas: list[CrossRule]
    umbral_requeridos: float
    umbral_opcionales: float

    @property
    def required_ids(self) -> list[str]:
        return [c.id for c in self.campos if c.required]

    @property
    def optional_ids(self) -> list[str]:
        return [c.id for c in self.campos if not c.required]

    def by_id(self, field_id: str) -> FieldRule | None:
        return next((c for c in self.campos if c.id == field_id), None)


def load_rules(path: Path) -> RuleSet:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    campos: list[FieldRule] = []
    for c in raw.get("campos_requeridos", []):
        campos.append(_field_from_dict(c, required=True))
    for c in raw.get("campos_opcionales", []):
        campos.append(_field_from_dict(c, required=False))

    cruzadas = [
        CrossRule(
            id=r["id"],
            descripcion=r.get("descripcion", ""),
            expresion=r.get("expresion"),
            severidad=r.get("severidad", "warning"),
            tipo=r.get("tipo"),
            tabla=r.get("tabla"),
        )
        for r in raw.get("reglas_cruzadas", [])
    ]

    umbral = raw.get("umbral_aprobacion", {})
    return RuleSet(
        version=raw.get("version", 1),
        campos=campos,
        cruzadas=cruzadas,
        umbral_requeridos=float(umbral.get("campos_requeridos_minimo", 1.0)),
        umbral_opcionales=float(umbral.get("campos_opcionales_minimo", 0.0)),
    )


def _field_from_dict(d: dict, required: bool) -> FieldRule:
    # Los sub-campos de un array heredan el estado de requerido del campo padre.
    item_fields = [
        _field_from_dict(item, required=required) for item in d.get("item_fields", [])
    ]
    return FieldRule(
        id=d["id"],
        descripcion=d.get("descripcion", ""),
        tipo=d.get("tipo", "string"),
        required=required,
        alias=d.get("alias", []),
        patron=d.get("patron"),
        rango=d.get("rango"),
        valores_permitidos=d.get("valores_permitidos"),
        item_fields=item_fields,
    )
