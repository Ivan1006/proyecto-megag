"""Robustez de la extracción de adjuntos y de los hilos.

Cubre los cuatro defectos que hacían que correos reales llegaran mal al mapper:
texto sin tope (que reventaba el contexto del modelo y tumbaba el run entero),
imágenes de firma coladas como adjuntos, tablas de PDF descartadas y tipos de
archivo perdidos en silencio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agropecuario.ingesta.extractor import extract
from agropecuario.ingesta.gmail_client import _es_imagen_incrustada
from agropecuario.ingesta.parsers import text_parser
from agropecuario.models import Attachment, EmailMessage


def _email(**kw) -> EmailMessage:
    base = dict(
        message_id="m1",
        thread_id="t1",
        sender="cliente@example.com",
        subject="Solicitud",
        received_at=datetime.now(UTC),
        body_plain="cuerpo",
        attachments=[],
    )
    base.update(kw)
    return EmailMessage(**base)


# --- topes de tamaño -------------------------------------------------------

def test_el_texto_total_se_recorta_al_limite(monkeypatch):
    """Sin tope, un hilo con PDFs largos revienta el contexto y falla el run."""
    from agropecuario import settings as settings_mod

    monkeypatch.setattr(
        settings_mod.get_settings(), "max_chars_total", 500, raising=False
    )
    extracted = extract(_email(body_plain="x" * 5_000))
    assert len(extracted.combined_text) < 1_000
    assert "recortado" in extracted.combined_text


def test_un_adjunto_gigante_no_se_come_todo_el_presupuesto(monkeypatch, tmp_path):
    """El tope por adjunto evita que uno solo desplace al resto del hilo."""
    from agropecuario import settings as settings_mod
    from agropecuario.ingesta import extractor as extractor_mod

    monkeypatch.setattr(
        settings_mod.get_settings(), "max_chars_por_adjunto", 100, raising=False
    )
    # OJO: hay que parchear el nombre EN el extractor, que hizo
    # `from .parsers import parse_attachment`; parchear `parsers` no le llega.
    monkeypatch.setattr(extractor_mod, "parse_attachment", lambda att: ("y" * 10_000, []))

    att = Attachment(
        filename="enorme.pdf", mime_type="application/pdf",
        size_bytes=1, local_path=tmp_path / "enorme.pdf",
    )
    texto = extract(_email(attachments=[att])).combined_text
    assert "cuerpo" in texto                    # el cuerpo sobrevive
    assert 0 < texto.count("y") <= 100          # se recortó, pero algo quedó
    assert "enorme.pdf" in texto                # y se sabe de qué adjunto viene


def test_sin_recorte_el_texto_queda_intacto():
    """El aviso de recorte solo aparece cuando de verdad se recortó."""
    extracted = extract(_email(body_plain="corto"))
    assert "recortado" not in extracted.combined_text


# --- imágenes de firma -----------------------------------------------------

@pytest.mark.parametrize(
    "headers",
    [
        [{"name": "Content-Disposition", "value": "inline; filename=image001.png"}],
        [{"name": "Content-ID", "value": "<image001@01D9>"}],
    ],
)
def test_las_imagenes_incrustadas_no_son_adjuntos(headers):
    """Los logos de firma no deben descargarse ni pasar por OCR."""
    part = {"mimeType": "image/png", "filename": "image001.png", "headers": headers}
    assert _es_imagen_incrustada(part) is True


def test_una_foto_adjuntada_de_verdad_si_es_adjunto():
    """Una imagen adjuntada a propósito (p. ej. foto del predio) sí se procesa."""
    part = {
        "mimeType": "image/jpeg",
        "filename": "predio.jpg",
        "headers": [{"name": "Content-Disposition", "value": "attachment; filename=predio.jpg"}],
    }
    assert _es_imagen_incrustada(part) is False


def test_un_pdf_marcado_inline_sigue_siendo_adjunto():
    """Solo se descartan imágenes: un PDF inline puede traer datos del crédito."""
    part = {
        "mimeType": "application/pdf",
        "filename": "balance.pdf",
        "headers": [{"name": "Content-Disposition", "value": "inline"}],
    }
    assert _es_imagen_incrustada(part) is False


# --- CSV / TXT (antes se perdían sin rastro) -------------------------------

def test_csv_con_punto_y_coma_se_lee_como_tabla(tmp_path):
    """En Colombia el separador suele ser `;` porque la coma es decimal."""
    csv_path = tmp_path / "balance.csv"
    csv_path.write_text("Concepto;Valor\nTotal activos;180000000\n", encoding="utf-8")

    texto, tablas = text_parser.parse(csv_path)
    assert "Total activos | 180000000" in texto
    assert tablas == [[["Concepto", "Valor"], ["Total activos", "180000000"]]]


def test_csv_con_coma_tambien_funciona(tmp_path):
    csv_path = tmp_path / "datos.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    _, tablas = text_parser.parse(csv_path)
    assert tablas == [[["a", "b"], ["1", "2"]]]


def test_csv_exportado_de_excel_en_windows_no_revienta(tmp_path):
    """Los exportes de Excel salen en cp1252 y romperían con utf-8 estricto."""
    csv_path = tmp_path / "cp1252.csv"
    csv_path.write_bytes("Concepto;Valor\nProducción;100\n".encode("cp1252"))
    texto, _ = text_parser.parse(csv_path)
    assert "Producción" in texto


def test_txt_se_devuelve_tal_cual(tmp_path):
    txt = tmp_path / "notas.txt"
    txt.write_text("Solicito crédito para café", encoding="utf-8")
    texto, tablas = text_parser.parse(txt)
    assert texto == "Solicito crédito para café"
    assert tablas == []


# --- fallos aislados -------------------------------------------------------

def test_un_adjunto_que_falla_no_tumba_el_resto(monkeypatch, tmp_path):
    """Un parser que revienta no puede llevarse por delante el correo entero."""
    from agropecuario.ingesta import extractor as extractor_mod

    def _explota(att):
        raise ValueError("pdf corrupto")

    monkeypatch.setattr(extractor_mod, "parse_attachment", _explota)
    att = Attachment(
        filename="roto.pdf", mime_type="application/pdf",
        size_bytes=1, local_path=tmp_path / "roto.pdf",
    )
    texto = extract(_email(attachments=[att])).combined_text
    assert "cuerpo" in texto
    assert "roto.pdf" not in texto


# --- agregación de hilos ---------------------------------------------------

def _msg(idx: int, attachments: list[Attachment]) -> EmailMessage:
    return EmailMessage(
        message_id=f"m{idx}",
        thread_id="t1",
        sender="cliente@example.com",
        subject="Solicitud",
        received_at=datetime(2026, 1, idx + 1, tzinfo=UTC),
        body_plain=f"correo {idx}",
        attachments=attachments,
    )


def _att(nombre: str, size: int) -> Attachment:
    return Attachment(
        filename=nombre,
        mime_type="application/pdf",
        size_bytes=size,
        local_path=Path("/tmp") / nombre,
    )


def test_el_mismo_archivo_reenviado_se_deduplica():
    """Mismo nombre y mismo tamaño: es el mismo documento, basta el último."""
    from agropecuario.ingesta.aggregator import aggregate_thread
    from agropecuario.models import EmailThread

    thread = EmailThread(
        thread_id="t1",
        messages=[_msg(0, [_att("balance.pdf", 100)]), _msg(1, [_att("balance.pdf", 100)])],
    )
    virtual, _ = aggregate_thread(thread)
    assert len(virtual.attachments) == 1


def test_dos_documentos_distintos_con_el_mismo_nombre_se_conservan():
    """Antes se pisaban por nombre y uno desaparecía sin rastro."""
    from agropecuario.ingesta.aggregator import aggregate_thread
    from agropecuario.models import EmailThread

    thread = EmailThread(
        thread_id="t1",
        messages=[_msg(0, [_att("balance.pdf", 100)]), _msg(1, [_att("balance.pdf", 250)])],
    )
    virtual, _ = aggregate_thread(thread)
    assert len(virtual.attachments) == 2
    assert {a.size_bytes for a in virtual.attachments} == {100, 250}


def test_el_hilo_conserva_los_cuerpos_de_todos_los_correos():
    from agropecuario.ingesta.aggregator import aggregate_thread
    from agropecuario.models import EmailThread

    thread = EmailThread(thread_id="t1", messages=[_msg(0, []), _msg(1, [])])
    virtual, contribuyentes = aggregate_thread(thread)
    assert "correo 0" in virtual.body_plain
    assert "correo 1" in virtual.body_plain
    assert contribuyentes == ["m0", "m1"]
