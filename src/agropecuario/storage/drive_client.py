"""Cliente de Google Drive para subir los entregables generados."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ..ingesta.gmail_client import GmailClient
from ..settings import get_settings

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveClient:
    """Reutiliza las credenciales Gmail (ambos scopes activos en el OAuth).

    Si ejecutas Drive sin Gmail previo, añade `drive.file` a los SCOPES de
    `GmailClient` antes de autenticar.
    """

    def __init__(self, gmail: GmailClient | None = None) -> None:
        self.settings = get_settings()
        self._gmail = gmail or GmailClient()
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._gmail.authenticate(interactive=False)
            creds = self._gmail.service._http.credentials  # type: ignore[attr-defined]
            self._service = build("drive", "v3", credentials=creds)
        return self._service

    def upload(self, local_path: Path, name: str | None = None) -> str:
        """Sube un archivo y devuelve su URL compartible."""
        folder_id = self.settings.drive_output_folder_id
        if not folder_id:
            raise RuntimeError("DRIVE_OUTPUT_FOLDER_ID no configurado")
        mime, _ = mimetypes.guess_type(str(local_path))
        metadata = {
            "name": name or local_path.name,
            "parents": [folder_id],
        }
        media = MediaFileUpload(str(local_path), mimetype=mime or "application/octet-stream")
        file = (
            self.service.files()
            .create(body=metadata, media_body=media, fields="id,webViewLink")
            .execute()
        )
        return file.get("webViewLink", "")
