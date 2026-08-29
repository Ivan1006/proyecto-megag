"""Persistencia SQLite para trazabilidad.

Diseño minimalista (un solo archivo de DB, 3 tablas):

- `runs`     : cada vez que el agente procesa un hilo, deja aquí un registro.
- `gaps`     : campos faltantes/inválidos detectados durante la validación.
- `messages` : mensajes individuales del hilo (para que la UI muestre el timeline).

Idempotencia: clave (thread_id, last_message_id). Si llega un mensaje nuevo
en el mismo hilo, se inserta un run nuevo (NO se actualiza el anterior),
de manera que la UI puede mostrar el histórico de iteraciones.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..logging_conf import get_logger
from ..settings import get_settings

logger = get_logger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id         TEXT NOT NULL,
    last_message_id   TEXT NOT NULL,
    -- pending|extracted|incomplete|approved|generated|delivered|failed
    status            TEXT NOT NULL,
    subject           TEXT,
    sender            TEXT,
    sender_name       TEXT,
    received_at       TEXT,                     -- ISO8601 del último mensaje
    started_at        TEXT NOT NULL,            -- ISO8601 inicio de procesamiento
    finished_at       TEXT,                     -- ISO8601 fin (null si en curso)
    duration_ms       INTEGER,
    fields_json       TEXT,                     -- JSON con los campos finagro mapeados
    completitud_req   REAL,
    completitud_opt   REAL,
    aprobado          INTEGER,                  -- 0|1
    excel_path        TEXT,
    pdf_path          TEXT,
    drive_excel_url   TEXT,
    drive_pdf_url     TEXT,
    error             TEXT,
    closed            INTEGER NOT NULL DEFAULT 0,  -- marcado como cerrado por el analista
    discrepancia_correo_web INTEGER,               -- 0|1|null: actividad correo vs web
    web_actividad_resumen   TEXT,                  -- resumen de la actividad según la web
    web_fuentes_json        TEXT,                  -- JSON: URLs consultadas
    UNIQUE(thread_id, last_message_id)
);

CREATE TABLE IF NOT EXISTS gaps (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL,
    field_id     TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    descripcion  TEXT,
    sugerencia   TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL,
    message_id    TEXT NOT NULL,
    sender        TEXT,
    sender_name   TEXT,
    subject       TEXT,
    received_at   TEXT,
    body_preview  TEXT,                          -- primeros ~500 chars
    attachments   TEXT,                          -- JSON: lista de nombres
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_thread ON runs(thread_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columnas añadidas después del esquema inicial. Se aplican con ALTER TABLE
# idempotente sobre bases existentes (para nuevas ya vienen en SCHEMA).
_RUNS_EXTRA_COLUMNS: dict[str, str] = {
    "discrepancia_correo_web": "INTEGER",
    "web_actividad_resumen": "TEXT",
    "web_fuentes_json": "TEXT",
}


def init_db(db_path: Path | None = None) -> None:
    with connection(db_path) as conn:
        conn.executescript(SCHEMA)
        ensure_columns(conn)
    logger.info("db.initialized", path=str(db_path or get_settings().db_path))


def ensure_columns(conn: sqlite3.Connection) -> None:
    """Añade columnas nuevas a `runs` que falten (migración sin destruir datos)."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}
    for col, decl in _RUNS_EXTRA_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {decl}")
            logger.info("db.column_added", column=col)


# ---------------------------------------------------------------------------
# API de runs
# ---------------------------------------------------------------------------

def create_run(
    thread_id: str,
    last_message_id: str,
    subject: str = "",
    sender: str = "",
    sender_name: str = "",
    received_at: datetime | None = None,
) -> int:
    """Inserta un run en estado `pending` y devuelve su id.

    Si ya existe el par (thread_id, last_message_id) reutiliza el id existente.
    """
    with connection() as conn:
        existing = conn.execute(
            "SELECT id FROM runs WHERE thread_id = ? AND last_message_id = ?",
            (thread_id, last_message_id),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO runs(thread_id, last_message_id, status, subject, sender,
                             sender_name, received_at, started_at)
            VALUES(?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                last_message_id,
                subject,
                sender,
                sender_name,
                received_at.isoformat() if received_at else None,
                _now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def update_run(run_id: int, **fields: Any) -> None:
    """Actualiza columnas arbitrarias del run. Convierte dicts/listas a JSON."""
    if not fields:
        return
    cols, values = [], []
    for k, v in fields.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, default=str)
        elif isinstance(v, bool):
            v = int(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        elif isinstance(v, Path):
            v = str(v)
        cols.append(f"{k} = ?")
        values.append(v)
    values.append(run_id)
    with connection() as conn:
        conn.execute(f"UPDATE runs SET {', '.join(cols)} WHERE id = ?", values)


def finish_run(run_id: int, status: str, error: str | None = None) -> None:
    """Marca un run como finalizado, calcula duración."""
    with connection() as conn:
        row = conn.execute(
            "SELECT started_at FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        duration_ms = None
        if row:
            try:
                started = datetime.fromisoformat(row["started_at"])
                duration_ms = int(
                    (datetime.now(UTC) - started).total_seconds() * 1000
                )
            except Exception:  # noqa: BLE001
                duration_ms = None
        conn.execute(
            """UPDATE runs SET status = ?, finished_at = ?, duration_ms = ?,
                                error = COALESCE(?, error)
                       WHERE id = ?""",
            (status, _now_iso(), duration_ms, error, run_id),
        )


def save_gaps(run_id: int, gaps: list[dict[str, Any]]) -> None:
    """Reemplaza las brechas del run (no las acumula).

    Un run se reprocesa varias veces sobre la misma fila (la idempotencia es por
    `thread_id + last_message_id`), así que insertar sin borrar dejaba la misma
    brecha repetida una vez por intento. El borrado va FUERA del early-return: un
    reproceso que resuelve todo debe dejar la lista vacía, no las brechas viejas.
    """
    with connection() as conn:
        conn.execute("DELETE FROM gaps WHERE run_id = ?", (run_id,))
        if not gaps:
            return
        conn.executemany(
            "INSERT INTO gaps(run_id, field_id, tipo, descripcion, sugerencia) "
            "VALUES(?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    g.get("field_id", ""),
                    g.get("tipo", ""),
                    g.get("descripcion"),
                    g.get("sugerencia"),
                )
                for g in gaps
            ],
        )


def save_messages(run_id: int, messages: list[dict[str, Any]]) -> None:
    """Reemplaza los mensajes del run (no los acumula). Ver `save_gaps`."""
    with connection() as conn:
        conn.execute("DELETE FROM messages WHERE run_id = ?", (run_id,))
        if not messages:
            return
        conn.executemany(
            """INSERT INTO messages(run_id, message_id, sender, sender_name,
                                     subject, received_at, body_preview, attachments)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_id,
                    m["message_id"],
                    m.get("sender"),
                    m.get("sender_name"),
                    m.get("subject"),
                    m.get("received_at"),
                    (m.get("body_preview") or "")[:500],
                    json.dumps(m.get("attachments", []), ensure_ascii=False),
                )
                for m in messages
            ],
        )


# ---------------------------------------------------------------------------
# Consultas para la UI
# ---------------------------------------------------------------------------

def list_runs(
    limit: int = 50,
    status: str | None = None,
    closed: int | None = None,
    in_progress: bool | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM runs"
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if closed is not None:
        where.append("closed = ?")
        params.append(closed)
    if in_progress is True:
        where.append("finished_at IS NULL")
    elif in_progress is False:
        where.append("finished_at IS NOT NULL")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    with connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_run(run_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        run = dict(row)
        run["gaps"] = [
            dict(g)
            for g in conn.execute(
                "SELECT * FROM gaps WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        ]
        run["messages"] = [
            dict(m)
            for m in conn.execute(
                "SELECT * FROM messages WHERE run_id = ? ORDER BY received_at",
                (run_id,),
            ).fetchall()
        ]
        return run


def get_latest_run_for_thread(thread_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE thread_id = ? ORDER BY started_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        return dict(row) if row else None


def mark_closed(run_id: int, closed: bool = True) -> None:
    with connection() as conn:
        conn.execute("UPDATE runs SET closed = ? WHERE id = ?", (int(closed), run_id))


def dashboard_metrics() -> dict[str, Any]:
    """KPIs agregados para la página principal."""
    with connection() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        success = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE status IN ('generated', 'delivered')"
        ).fetchone()["n"]
        failed = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE status = 'failed'"
        ).fetchone()["n"]
        incomplete = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE status = 'incomplete'"
        ).fetchone()["n"]
        in_progress = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE finished_at IS NULL"
        ).fetchone()["n"]
        avg_ms = conn.execute(
            "SELECT AVG(duration_ms) AS m FROM runs WHERE duration_ms IS NOT NULL"
        ).fetchone()["m"]
        last_7 = conn.execute(
            "SELECT COUNT(*) AS n FROM runs "
            "WHERE started_at >= datetime('now', '-7 days')"
        ).fetchone()["n"]
        last_24h = conn.execute(
            "SELECT COUNT(*) AS n FROM runs "
            "WHERE started_at >= datetime('now', '-1 day')"
        ).fetchone()["n"]
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "incomplete": incomplete,
            "in_progress": in_progress,
            "last_7_days": last_7,
            "last_24h": last_24h,
            "avg_duration_ms": int(avg_ms) if avg_ms else None,
            "success_rate": (success / total) if total else 0.0,
        }
