"""Dispatcher de parsers por tipo MIME / extensión."""

from __future__ import annotations

from typing import Any

from ...models import Attachment
from . import excel_parser, image_parser, pdf_parser, word_parser


def parse_attachment(att: Attachment) -> tuple[str, list[list[list[Any]]]]:
    """Devuelve (texto, tablas). Tablas es una lista de matrices."""
    name = att.filename.lower()
    mime = att.mime_type.lower()

    if name.endswith(".pdf") or "pdf" in mime:
        return pdf_parser.parse(att.local_path), []
    if name.endswith((".xlsx", ".xlsm", ".xls")) or "spreadsheet" in mime or "excel" in mime:
        text, tables = excel_parser.parse(att.local_path)
        return text, tables
    if name.endswith((".docx", ".doc")) or "word" in mime or "document" in mime:
        return word_parser.parse(att.local_path), []
    if name.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")) or mime.startswith("image/"):
        return image_parser.parse(att.local_path), []

    return "", []
