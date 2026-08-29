"""Extractor: combina cuerpo del correo + texto de adjuntos en un bloque único.

El resultado alimenta el prompt del `mapper`, así que aquí se aplican los topes
de tamaño: sin ellos, un hilo con un par de PDF largos supera el contexto del
modelo y el run falla entero en vez de degradar.

Cuando algo se recorta se deja una marca visible en el propio texto, para que el
LLM sepa que está viendo un fragmento y no el documento completo, y un aviso en
el log para que el analista pueda revisar el adjunto a mano.
"""

from __future__ import annotations

from ..logging_conf import get_logger
from ..models import EmailMessage, ExtractedContent
from ..settings import get_settings
from .parsers import parse_attachment

logger = get_logger(__name__)

_AVISO_RECORTE = "\n\n[... texto recortado por longitud: revisar el adjunto original ...]"


def _truncar(texto: str, limite: int) -> tuple[str, bool]:
    """Recorta a `limite` caracteres dejando constancia dentro del texto."""
    if limite <= 0 or len(texto) <= limite:
        return texto, False
    return texto[:limite] + _AVISO_RECORTE, True


def extract(email: EmailMessage) -> ExtractedContent:
    """Parsea cada adjunto y concatena con el cuerpo del correo."""
    settings = get_settings()
    parts: list[str] = []
    if email.body_plain:
        parts.append(f"=== CUERPO DEL CORREO ===\n{email.body_plain}")

    for att in email.attachments:
        try:
            text, tables = parse_attachment(att)
            att.extracted_text = text
            att.extracted_tables = tables
            if not text:
                # Ni parser para el tipo, ni contenido legible. Antes se perdía
                # en silencio; ahora queda registrado para poder revisarlo.
                logger.warning(
                    "extractor.adjunto_sin_texto",
                    filename=att.filename,
                    mime=att.mime_type,
                )
                continue
            text, recortado = _truncar(text, settings.max_chars_por_adjunto)
            if recortado:
                logger.warning(
                    "extractor.adjunto_recortado",
                    filename=att.filename,
                    limite=settings.max_chars_por_adjunto,
                )
            parts.append(f"=== ADJUNTO: {att.filename} ===\n{text}")
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "extractor.parse_failed", filename=att.filename, error=str(e)
            )

    combined = "\n\n".join(parts)
    combined, recortado = _truncar(combined, settings.max_chars_total)
    if recortado:
        logger.warning(
            "extractor.texto_total_recortado",
            limite=settings.max_chars_total,
            adjuntos=len(email.attachments),
        )
    return ExtractedContent(email=email, combined_text=combined, fields_raw={})
