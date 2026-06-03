"""Agregador de hilos Gmail.

Convierte un `EmailThread` (varios correos del mismo asunto, en orden
cronológico) en un `EmailMessage` "virtual" listo para el extractor:

- El `body_plain` resultante concatena cada mensaje con un encabezado
  que indica fecha, remitente y posición (`[msg 1/4 ...]`).  Eso le da
  al LLM la pista para detectar correcciones.
- Los adjuntos se deduplican por nombre quedándose con el **más reciente**
  (un PDF reenviado en el correo 3 reemplaza al del correo 1).
- Los metadatos del primer mensaje (remitente, asunto) se conservan,
  pero `received_at` apunta al último mensaje del hilo.
"""

from __future__ import annotations

from ..logging_conf import get_logger
from ..models import Attachment, EmailMessage, EmailThread

logger = get_logger(__name__)


def aggregate_thread(thread: EmailThread) -> tuple[EmailMessage, list[str]]:
    """Devuelve un EmailMessage "virtual" + lista de message_ids contribuyentes.

    Si el hilo tiene un solo mensaje, lo devuelve casi tal cual (con el
    encabezado igualmente, para que el LLM tenga el contexto temporal).
    """
    if not thread.messages:
        raise ValueError("El hilo no tiene mensajes")

    msgs = thread.messages
    first = msgs[0]
    last = msgs[-1]

    parts: list[str] = []
    for idx, m in enumerate(msgs, start=1):
        header = (
            f"\n=== [Correo {idx}/{len(msgs)}] "
            f"{m.received_at:%Y-%m-%d %H:%M} — {m.sender_name or m.sender} ===\n"
            f"Asunto: {m.subject}\n"
        )
        body = (m.body_plain or "").strip()
        parts.append(header + body)

    combined_body = "\n".join(parts).strip()

    # Dedupe de adjuntos: el más reciente con el mismo filename gana.
    by_name: dict[str, tuple[int, Attachment]] = {}
    for idx, m in enumerate(msgs):
        for att in m.attachments:
            prev = by_name.get(att.filename)
            if prev is None or idx > prev[0]:
                by_name[att.filename] = (idx, att)

    deduped = [a for _, a in by_name.values()]
    if len(deduped) != sum(len(m.attachments) for m in msgs):
        logger.info(
            "aggregator.attachments_deduped",
            input=sum(len(m.attachments) for m in msgs),
            output=len(deduped),
        )

    virtual = EmailMessage(
        message_id=last.message_id,
        thread_id=thread.thread_id,
        sender=first.sender,
        sender_name=first.sender_name,
        recipients=first.recipients,
        subject=first.subject,
        received_at=last.received_at,
        body_plain=combined_body,
        body_html=None,
        attachments=deduped,
        labels=list({lbl for m in msgs for lbl in m.labels}),
    )

    contributing = [m.message_id for m in msgs]
    return virtual, contributing
