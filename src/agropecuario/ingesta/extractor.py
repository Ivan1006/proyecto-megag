"""Extractor: combina cuerpo del correo + texto de adjuntos en un bloque único."""

from __future__ import annotations

from ..logging_conf import get_logger
from ..models import EmailMessage, ExtractedContent
from .parsers import parse_attachment

logger = get_logger(__name__)


def extract(email: EmailMessage) -> ExtractedContent:
    """Parsea cada adjunto y concatena con el cuerpo del correo."""
    parts: list[str] = []
    if email.body_plain:
        parts.append(f"=== CUERPO DEL CORREO ===\n{email.body_plain}")

    for att in email.attachments:
        try:
            text, tables = parse_attachment(att)
            att.extracted_text = text
            att.extracted_tables = tables
            if text:
                parts.append(f"=== ADJUNTO: {att.filename} ===\n{text}")
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "extractor.parse_failed", filename=att.filename, error=str(e)
            )

    combined = "\n\n".join(parts)
    return ExtractedContent(email=email, combined_text=combined, fields_raw={})
