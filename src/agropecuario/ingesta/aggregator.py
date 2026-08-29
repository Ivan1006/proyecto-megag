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

    # Dedupe de adjuntos: gana el más reciente con el mismo nombre Y tamaño.
    #
    # El tamaño es lo que evita perder documentos: con solo el nombre, dos
    # adjuntos distintos que se llamen igual —"balance.pdf" de dos socios,
    # "escaneado.pdf" de dos correos— se pisaban y uno desaparecía sin rastro.
    # Si difieren en bytes son documentos distintos y se conservan los dos; si
    # coinciden es el mismo archivo reenviado y basta con el último.
    by_key: dict[tuple[str, int], tuple[int, Attachment]] = {}
    for idx, m in enumerate(msgs):
        for att in m.attachments:
            key = (att.filename, att.size_bytes)
            prev = by_key.get(key)
            if prev is None or idx > prev[0]:
                by_key[key] = (idx, att)

    deduped = [a for _, a in by_key.values()]
    entrada = sum(len(m.attachments) for m in msgs)
    if len(deduped) != entrada:
        logger.info(
            "aggregator.attachments_deduped",
            input=entrada,
            output=len(deduped),
            conservados=[a.filename for a in deduped],
        )

    # Mismo nombre y distinto tamaño: se conservan ambos, pero conviene avisar
    # porque al analista le va a extrañar ver el archivo dos veces.
    repetidos = sorted(_nombres_repetidos(by_key))
    if repetidos:
        logger.info("aggregator.mismo_nombre_distinto_contenido", nombres=repetidos)

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


def _nombres_repetidos(by_key: dict[tuple[str, int], object]) -> set[str]:
    """Nombres que aparecen con más de un tamaño (documentos distintos)."""
    vistos: dict[str, int] = {}
    for nombre, _ in by_key:
        vistos[nombre] = vistos.get(nombre, 0) + 1
    return {n for n, veces in vistos.items() if veces > 1}
