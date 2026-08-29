"""Dispatcher de parsers por tipo MIME / extensión."""

from __future__ import annotations

from typing import Any

from ...logging_conf import get_logger
from ...models import Attachment
from . import excel_parser, image_parser, pdf_parser, text_parser, word_parser

logger = get_logger(__name__)


def parse_attachment(att: Attachment) -> tuple[str, list[list[list[Any]]]]:
    """Devuelve (texto, tablas). Tablas es una lista de matrices."""
    name = att.filename.lower()
    mime = att.mime_type.lower()

    if name.endswith(".pdf") or "pdf" in mime:
        # El PDF SÍ devuelve tablas: los estados financieros vienen así.
        return pdf_parser.parse(att.local_path)
    if name.endswith((".xlsx", ".xlsm", ".xls")) or "spreadsheet" in mime or "excel" in mime:
        return excel_parser.parse(att.local_path)
    if name.endswith((".docx", ".doc")) or "word" in mime or "document" in mime:
        return word_parser.parse(att.local_path), []
    if name.endswith((".csv", ".tsv", ".txt")) or mime.startswith("text/"):
        return text_parser.parse(att.local_path)
    if name.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")) or mime.startswith("image/"):
        return image_parser.parse(att.local_path), []

    # Sin parser: se registra en vez de devolver vacío en silencio, que hacía
    # indistinguible "no sé leer esto" de "esto no tenía texto".
    logger.warning("parsers.tipo_no_soportado", filename=att.filename, mime=att.mime_type)
    return "", []
