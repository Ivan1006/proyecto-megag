"""Reprocesar un hilo no debe acumular filas hijas.

La idempotencia de `create_run` es por `(thread_id, last_message_id)`: reprocesar
reutiliza la MISMA fila de `runs`. Las tablas hijas se insertaban sin borrar las
anteriores, así que cada intento repetía las mismas brechas y los mismos mensajes.
Detectado con datos reales: un run con 162 filas de brechas para 24 campos
distintos y 8 mensajes para un único correo.
"""

from __future__ import annotations

import pytest

from agropecuario.storage import db


@pytest.fixture
def db_temporal(monkeypatch, tmp_path):
    """BD limpia por test, sin tocar la del proyecto."""
    from agropecuario import settings as settings_mod

    monkeypatch.setattr(
        settings_mod.get_settings(), "db_path", tmp_path / "test.sqlite", raising=False
    )
    db.init_db()
    return db.create_run(
        thread_id="t1", last_message_id="m1", subject="Asunto",
        sender="a@b.com", sender_name="A", received_at=None,
    )


def _gaps(n: int) -> list[dict]:
    return [{"field_id": f"campo_{i}", "tipo": "faltante"} for i in range(n)]


def _messages(ids: list[str]) -> list[dict]:
    return [
        {"message_id": i, "sender": "a@b.com", "sender_name": "A",
         "subject": "s", "received_at": "2026-01-01", "body_preview": "x",
         "attachments": []}
        for i in ids
    ]


def _contar(tabla: str, run_id: int) -> int:
    with db.connection() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {tabla} WHERE run_id=?", (run_id,)).fetchone()[0]


def test_reprocesar_no_duplica_brechas(db_temporal):
    run_id = db_temporal
    db.save_gaps(run_id, _gaps(3))
    db.save_gaps(run_id, _gaps(3))
    db.save_gaps(run_id, _gaps(3))
    assert _contar("gaps", run_id) == 3


def test_reprocesar_sin_brechas_borra_las_viejas(db_temporal):
    """Si el reproceso resuelve todo, no pueden quedar las brechas anteriores."""
    run_id = db_temporal
    db.save_gaps(run_id, _gaps(3))
    db.save_gaps(run_id, [])
    assert _contar("gaps", run_id) == 0


def test_reprocesar_refleja_las_brechas_nuevas(db_temporal):
    """El reemplazo deja exactamente lo del último intento, no la unión."""
    run_id = db_temporal
    db.save_gaps(run_id, _gaps(5))
    db.save_gaps(run_id, _gaps(2))
    assert _contar("gaps", run_id) == 2


def test_reprocesar_no_duplica_mensajes(db_temporal):
    run_id = db_temporal
    db.save_messages(run_id, _messages(["m1"]))
    db.save_messages(run_id, _messages(["m1"]))
    assert _contar("messages", run_id) == 1


def test_un_hilo_que_crece_refleja_todos_sus_correos(db_temporal):
    """Si al hilo llegan correos nuevos, el reproceso los recoge todos."""
    run_id = db_temporal
    db.save_messages(run_id, _messages(["m1"]))
    db.save_messages(run_id, _messages(["m1", "m2"]))
    assert _contar("messages", run_id) == 2
