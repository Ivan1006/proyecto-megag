"""Carga de la plantilla YAML y helpers para secciones."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Section:
    id: str
    titulo: str
    campos: list[str]
    generado_por_llm: bool = False
    prompt: str | None = None


@dataclass
class CalculatedSpec:
    id: str
    tipo: str
    formula: str | None
    formato: str | None = None
    descripcion: str | None = None


@dataclass
class Template:
    version: int
    titulo_formato: str
    secciones: list[Section]
    calculados: list[CalculatedSpec]
    salida: dict[str, Any]


def load_template(path: Path) -> Template:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    proyecto = raw.get("proyecto", {})
    secciones = [
        Section(
            id=s["id"],
            titulo=s.get("titulo", s["id"]),
            campos=s.get("campos", []),
            generado_por_llm=s.get("generado_por_llm", False),
            prompt=s.get("prompt"),
        )
        for s in raw.get("secciones", [])
    ]
    calculados = [
        CalculatedSpec(
            id=c["id"],
            tipo=c.get("tipo", "number"),
            formula=c.get("formula"),
            formato=c.get("formato"),
            descripcion=c.get("descripcion"),
        )
        for c in raw.get("calculados", [])
    ]
    return Template(
        version=raw.get("version", 1),
        titulo_formato=proyecto.get("titulo_formato", "Proyecto Agropecuario"),
        secciones=secciones,
        calculados=calculados,
        salida=raw.get("salida", {}),
    )
