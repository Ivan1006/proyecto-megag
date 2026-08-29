"""Persistencia SQLite del estado por proyecto.

La idempotencia se garantiza usando `message_id` como UNIQUE: reprocesar el
mismo correo es un no-op salvo que el estado cambie explícitamente.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..models import ProjectRecord, ProjectStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    message_id TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at);
"""


class ProjectStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert(self, record: ProjectRecord) -> ProjectRecord:
        record.updated_at = datetime.now(UTC)
        payload = record.model_dump_json(exclude={"id", "message_id", "status", "error"})
        self.conn.execute(
            """
            INSERT INTO projects (id, message_id, status, created_at, updated_at, payload, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                status=excluded.status,
                updated_at=excluded.updated_at,
                payload=excluded.payload,
                error=excluded.error
            """,
            (
                record.id,
                record.message_id,
                record.status.value,
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
                payload,
                record.error,
            ),
        )
        self.conn.commit()
        return record

    def get_by_message(self, message_id: str) -> ProjectRecord | None:
        row = self.conn.execute(
            "SELECT id, message_id, status, created_at, updated_at, payload, error "
            "FROM projects WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def new_record(self, message_id: str) -> ProjectRecord:
        now = datetime.now(UTC)
        return ProjectRecord(
            id=str(uuid.uuid4()),
            message_id=message_id,
            status=ProjectStatus.PENDING,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _row_to_record(row) -> ProjectRecord:
        id_, message_id, status, created, updated, payload, error = row
        data = json.loads(payload)
        data.update(
            {
                "id": id_,
                "message_id": message_id,
                "status": status,
                "created_at": created,
                "updated_at": updated,
                "error": error,
            }
        )
        return ProjectRecord.model_validate(data)
