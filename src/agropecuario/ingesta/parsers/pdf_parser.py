"""Parser de PDFs. Intenta extracción nativa con pdfplumber; OCR si falla."""

from __future__ import annotations

from pathlib import Path

import pdfplumber


def parse(path: Path) -> str:
    text_parts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)
    text = "\n".join(text_parts).strip()
    if not text:
        # PDF escaneado: delegar a OCR
        from . import image_parser

        text = image_parser.parse_pdf_via_ocr(path)
    return text
