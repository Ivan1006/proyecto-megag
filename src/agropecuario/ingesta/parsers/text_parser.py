"""Parser de adjuntos de texto plano: CSV, TSV y TXT.

Antes caían en el `return "", []` del dispatcher y desaparecían sin dejar rastro,
pese a que un balance exportado a CSV es un adjunto perfectamente esperable.

Los CSV se leen como tabla (respetando el delimitador real, que en Colombia suele
ser `;` porque la coma es el separador decimal) y se renderizan igual que las
tablas de PDF y Excel, para que el LLM vea una sola forma de tabla en todo el
prompt. El TXT se devuelve tal cual.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ...logging_conf import get_logger

logger = get_logger(__name__)

# Codificaciones a intentar, en orden. Los exportes de Excel en Windows salen en
# cp1252 y reventarían con utf-8 estricto.
_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def parse(path: Path) -> tuple[str, list[list[list[Any]]]]:
    """Devuelve (texto, tablas). `tablas` va vacía para .txt."""
    raw = _leer(path)
    if path.suffix.lower() not in (".csv", ".tsv"):
        return raw, []

    filas = _parse_delimitado(raw, path.suffix.lower())
    if not filas:
        return raw, []
    cuerpo = "\n".join(" | ".join(fila) for fila in filas)
    return f"[Tabla — {path.name}]\n{cuerpo}", [filas]


def _leer(path: Path) -> str:
    for enc in _ENCODINGS:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    # Último recurso: no perder el adjunto por un byte suelto.
    logger.warning("text_parser.encoding_desconocido", archivo=path.name)
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_delimitado(raw: str, sufijo: str) -> list[list[str]]:
    if sufijo == ".tsv":
        delimitador = "\t"
    else:
        try:
            # El Sniffer acierta con `;` vs `,`, que es la ambigüedad real aquí.
            delimitador = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimitador = ","
    return [
        [celda.strip() for celda in fila]
        for fila in csv.reader(raw.splitlines(), delimiter=delimitador)
        if any(celda.strip() for celda in fila)
    ]
