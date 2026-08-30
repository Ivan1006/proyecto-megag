"""El seed de demo no debe prometer descargas que no existen.

`seed-demo` guardaba en `runs` la ruta a `solicitud_credito.xlsx` sin crear el
archivo, así que el dashboard ofrecía el botón de descarga y siempre respondía
"No hay excel para este run". Una demo que promete lo que no puede cumplir es
peor que una sin descarga.

La invariante que fijan estos tests: **la ruta se guarda solo si el archivo quedó
en disco**.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agropecuario.storage.seed import _entregables

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def salida_temporal(monkeypatch, tmp_path):
    from agropecuario import settings as settings_mod

    monkeypatch.setattr(
        settings_mod.get_settings(), "output_dir", tmp_path, raising=False
    )
    return tmp_path


def _sample(status: str) -> dict:
    demo = json.loads(
        (PROJECT_ROOT / "data" / "samples" / "credito_demo.json").read_text(encoding="utf-8")
    )
    return {"status": status, "thread_id": "tg-test", "fields": demo}


@pytest.mark.parametrize("status", ["incomplete", "failed", "extracted", "pending"])
def test_un_run_sin_entregables_no_guarda_rutas(salida_temporal, status):
    assert _entregables(_sample(status)) == {"excel_path": None, "pdf_path": None}


def test_un_run_generated_crea_el_excel_de_verdad(salida_temporal):
    rutas = _entregables(_sample("generated"))
    assert rutas["excel_path"] is not None
    assert Path(rutas["excel_path"]).exists()


def test_toda_ruta_guardada_apunta_a_un_archivo_existente(salida_temporal):
    """La invariante: si hay ruta, hay archivo. Es lo que el 404 destapó.

    El PDF depende de LibreOffice, así que puede quedar en None si no está
    instalado (en CI no lo está) — pero nunca puede quedar una ruta colgando.
    """
    rutas = _entregables(_sample("generated"))
    for ruta in rutas.values():
        if ruta is not None:
            assert Path(ruta).exists(), f"ruta guardada sin archivo: {ruta}"


def test_si_el_render_falla_no_queda_ruta_colgando(salida_temporal, monkeypatch):
    """Un fallo al rellenar el Excel no puede dejar la promesa de descarga."""
    from agropecuario.storage import seed as seed_mod

    def _explota(*a, **kw):
        raise RuntimeError("template corrupto")

    monkeypatch.setattr(
        "agropecuario.generacion.excel_writer.render_excel", _explota
    )
    assert seed_mod._entregables(_sample("generated")) == {
        "excel_path": None,
        "pdf_path": None,
    }
