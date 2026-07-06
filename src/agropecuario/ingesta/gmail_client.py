"""Cliente Gmail: autenticación OAuth2, listado y descarga de correos."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Iterable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ..logging_conf import get_logger
from ..models import Attachment, EmailMessage
from ..settings import get_settings

logger = get_logger(__name__)

# `gmail.modify` es un superconjunto que cubre lectura, envío de respuestas
# (`messages.send`) y modificación de etiquetas (`threads.modify` / `labels`).
# Es el único scope necesario y arregla el `403 insufficientPermissions` al
# marcar el hilo como `bot-procesado` (sin él, `watch-bot` reprocesaba el mismo
# hilo en cada pasada). Cambiar esta lista invalida el token cacheado y obliga a
# re-autenticar: `agropecuario auth`.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._service = None

    def authenticate(self, interactive: bool = True) -> None:
        """Carga credenciales cacheadas o lanza flujo OAuth."""
        creds: Credentials | None = None
        token = self.settings.google_token_path
        if token.exists():
            creds = Credentials.from_authorized_user_file(str(token), SCOPES)
        if not creds or not creds.valid:
            refreshed = False
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    refreshed = True
                except RefreshError as e:
                    # El refresh token caducó (típico en modo Testing de Google,
                    # 7 días). Descartamos el token muerto y caemos al login.
                    logger.warning("gmail.refresh_failed", error=str(e))
                    creds = None
            if not refreshed:
                if interactive:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.settings.google_client_secrets), SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                else:
                    raise RuntimeError("No hay credenciales válidas y modo no-interactivo")
            token.parent.mkdir(parents=True, exist_ok=True)
            token.write_text(creds.to_json())
        self._service = build("gmail", "v1", credentials=creds)
        logger.info("gmail.authenticated")

    @property
    def service(self):
        if self._service is None:
            self.authenticate(interactive=False)
        return self._service

    def list_messages(self, query: str | None = None, max_results: int = 20) -> list[str]:
        """Devuelve IDs de mensajes que matchean el query."""
        q = query or self.settings.gmail_query_filter
        resp = (
            self.service.users()
            .messages()
            .list(userId="me", q=q, maxResults=max_results)
            .execute()
        )
        return [m["id"] for m in resp.get("messages", [])]

    def fetch_message(self, message_id: str, download_dir: Path | None = None) -> EmailMessage:
        """Descarga mensaje + adjuntos y devuelve un `EmailMessage`."""
        raw = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return self._parse_message(raw, download_dir or self.settings.temp_dir)

    # ------------------------------------------------------------------
    # Hilos y etiquetas (trigger por etiqueta "bot")
    # ------------------------------------------------------------------

    def get_or_create_label(self, name: str) -> str:
        """Devuelve el ID de la etiqueta `name`, creándola si no existe."""
        existing = self.service.users().labels().list(userId="me").execute()
        for lbl in existing.get("labels", []):
            if lbl.get("name", "").lower() == name.lower():
                return lbl["id"]
        created = (
            self.service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        logger.info("gmail.label_created", name=name, id=created["id"])
        return created["id"]

    def list_threads_with_label(
        self, label_name: str, exclude_label: str | None = None, max_results: int = 50
    ) -> list[str]:
        """Devuelve IDs de hilos que tienen `label_name` (y opcionalmente NO `exclude_label`).

        Útil para encontrar hilos marcados con "bot" pero que aún no estén "bot-procesado".
        """
        q = f'label:"{label_name}"'
        if exclude_label:
            q += f' -label:"{exclude_label}"'
        resp = (
            self.service.users()
            .threads()
            .list(userId="me", q=q, maxResults=max_results)
            .execute()
        )
        return [t["id"] for t in resp.get("threads", [])]

    def fetch_thread(
        self, thread_id: str, download_dir: Path | None = None
    ) -> list[EmailMessage]:
        """Descarga todos los mensajes del hilo, ordenados cronológicamente."""
        raw = (
            self.service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
        dl = download_dir or self.settings.temp_dir
        messages = [self._parse_message(m, dl) for m in raw.get("messages", [])]
        messages.sort(key=lambda m: m.received_at)
        return messages

    def add_label_to_thread(self, thread_id: str, label_id: str) -> None:
        self.service.users().threads().modify(
            userId="me", id=thread_id, body={"addLabelIds": [label_id]}
        ).execute()

    def remove_label_from_thread(self, thread_id: str, label_id: str) -> None:
        self.service.users().threads().modify(
            userId="me", id=thread_id, body={"removeLabelIds": [label_id]}
        ).execute()

    def send_reply(self, thread_id: str, to: str, subject: str, body: str) -> None:
        """Envía una respuesta al remitente dentro del mismo thread."""
        from email.mime.text import MIMEText

        msg = MIMEText(body, _charset="utf-8")
        msg["To"] = to
        msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        self.service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": thread_id}
        ).execute()
        logger.info("gmail.reply_sent", thread_id=thread_id, to=to)

    def iter_new_messages(self) -> Iterable[str]:
        """Loop de polling para modo watch."""
        raise NotImplementedError("Implementar con historyId o polling periódico")

    def _parse_message(self, raw: dict, download_dir: Path) -> EmailMessage:
        headers = {h["name"].lower(): h["value"] for h in raw["payload"].get("headers", [])}
        sender_name, sender_email = parseaddr(headers.get("from", ""))
        recipients = [parseaddr(r)[1] for r in headers.get("to", "").split(",") if r]
        received_ts = int(raw.get("internalDate", "0")) / 1000
        received_at = datetime.fromtimestamp(received_ts, tz=timezone.utc)

        body_plain, body_html, attachments = self._walk_parts(
            raw["payload"], raw["id"], download_dir
        )

        return EmailMessage(
            message_id=raw["id"],
            thread_id=raw["threadId"],
            sender=sender_email,
            sender_name=sender_name or None,
            recipients=recipients,
            subject=headers.get("subject", ""),
            received_at=received_at,
            body_plain=body_plain,
            body_html=body_html,
            attachments=attachments,
            labels=raw.get("labelIds", []),
        )

    def _walk_parts(
        self, payload: dict, message_id: str, download_dir: Path
    ) -> tuple[str, str | None, list[Attachment]]:
        body_plain: list[str] = []
        body_html: list[str] = []
        attachments: list[Attachment] = []

        def walk(part: dict) -> None:
            mime = part.get("mimeType", "")
            filename = part.get("filename")
            body = part.get("body", {})
            if filename:
                att_id = body.get("attachmentId")
                if att_id:
                    path = self._download_attachment(message_id, att_id, filename, download_dir)
                    attachments.append(
                        Attachment(
                            filename=filename,
                            mime_type=mime,
                            size_bytes=body.get("size", 0),
                            local_path=path,
                        )
                    )
            elif mime == "text/plain" and body.get("data"):
                body_plain.append(_b64(body["data"]))
            elif mime == "text/html" and body.get("data"):
                body_html.append(_b64(body["data"]))
            for sub in part.get("parts", []) or []:
                walk(sub)

        walk(payload)
        return (
            "\n".join(body_plain),
            "\n".join(body_html) if body_html else None,
            attachments,
        )

    def _download_attachment(
        self, message_id: str, attachment_id: str, filename: str, download_dir: Path
    ) -> Path:
        download_dir.mkdir(parents=True, exist_ok=True)
        att = (
            self.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = _b64_bytes(att["data"])
        path = download_dir / f"{message_id}__{filename}"
        path.write_bytes(data)
        return path


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def _b64_bytes(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("utf-8"))
