"""OCR de imágenes y PDFs escaneados con Tesseract."""

from __future__ import annotations

from pathlib import Path

import pytesseract
from PIL import Image


def parse(path: Path, lang: str = "spa") -> str:
    img = Image.open(str(path))
    return pytesseract.image_to_string(img, lang=lang)


def parse_pdf_via_ocr(path: Path, lang: str = "spa") -> str:
    """OCR página a página de un PDF escaneado.

    Requiere poppler + pdf2image en el entorno. Separado para no cargar
    dependencias pesadas cuando el PDF tiene capa de texto nativa.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        return ""
    pages = convert_from_path(str(path))
    return "\n\n".join(pytesseract.image_to_string(p, lang=lang) for p in pages)
