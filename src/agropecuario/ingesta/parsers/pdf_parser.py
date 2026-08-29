"""Parser de PDFs. Extracción nativa con pdfplumber; OCR si no hay capa de texto.

Además del texto corrido se extraen las **tablas**: los estados financieros que
vienen adjuntos (balance, estado de resultados) son tablas, y `extract_text()`
las aplana en una sopa de números donde se pierde qué cifra pertenece a qué
concepto. Reconstruirlas en filas separadas por `|` le da al LLM la estructura
que necesita para no confundir activos con pasivos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber

from ...logging_conf import get_logger

logger = get_logger(__name__)


def parse(path: Path) -> tuple[str, list[list[list[Any]]]]:
    """Devuelve (texto, tablas). El texto ya incluye las tablas renderizadas."""
    text_parts: list[str] = []
    tables: list[list[list[Any]]] = []

    with pdfplumber.open(str(path)) as pdf:
        for numero, page in enumerate(pdf.pages, start=1):
            text_parts.append(page.extract_text() or "")
            for tabla in page.extract_tables() or []:
                filas = [[("" if c is None else str(c).strip()) for c in fila] for fila in tabla]
                if not any(any(c for c in fila) for filas_ in (filas,) for fila in filas_):
                    continue  # tabla detectada pero vacía
                tables.append(filas)
                text_parts.append(_render_tabla(filas, numero))

    text = "\n".join(p for p in text_parts if p).strip()
    if not text:
        # PDF escaneado: delegar a OCR (que no sabe de tablas).
        from . import image_parser

        logger.info("pdf.sin_capa_de_texto_usando_ocr", archivo=path.name)
        text = image_parser.parse_pdf_via_ocr(path)

    return text, tables


def _render_tabla(filas: list[list[str]], pagina: int) -> str:
    """Tabla como filas separadas por `|`, con encabezado de procedencia."""
    cuerpo = "\n".join(" | ".join(fila) for fila in filas)
    return f"[Tabla — página {pagina}]\n{cuerpo}"
