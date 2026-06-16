"""Tests del RAG del Manual de Servicios (índice + retriever + cableado).

No tocan red ni API key: la función de embedding y la extracción del PDF se
inyectan/monkeypatchean con stubs deterministas.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from agropecuario.catalogo import manual_index
from agropecuario.catalogo.code_resolver import CodeResolver
from agropecuario.catalogo.loader import Catalogo, CatalogoEntry
from agropecuario.catalogo.manual_index import _split_text, build_index
from agropecuario.catalogo.manual_retriever import ManualRetriever

# Embedding fake: cuenta palabras clave → coseno separa bien los temas.
_VOCAB = ["cafe", "ganado", "riego"]


def _fake_embed(textos: Sequence[str]) -> list[list[float]]:
    return [[float(t.lower().count(w)) for w in _VOCAB] for t in textos]


def _fake_pages() -> list[tuple[int, str]]:
    return [
        (1, "El destino de cafe financia renovacion de cafe y siembra de cafe."),
        (2, "El destino de ganado financia compra de ganado de ceba."),
        (3, "El destino de riego financia sistemas de riego tecnificado."),
    ]


# --- chunking -------------------------------------------------------------


def test_split_text_trocea_con_solape():
    texto = "palabra " * 300  # ~2400 chars → varios chunks
    chunks = _split_text(texto, size=1000, overlap=150)
    assert len(chunks) > 1
    # Cada chunk respeta el tope de tamaño.
    assert all(len(c) <= 1000 for c in chunks)


def test_split_text_vacio_devuelve_lista_vacia():
    assert _split_text("   ", size=1000, overlap=150) == []


# --- build_index + retriever (roundtrip) ----------------------------------


def test_build_index_y_recupera_fragmento_relevante(tmp_path, monkeypatch):
    monkeypatch.setattr(manual_index, "extract_pages", lambda _p: _fake_pages())
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-fake")
    index_dir = tmp_path / "idx"

    meta = build_index(pdf_path=pdf, out_dir=index_dir, embed=_fake_embed)
    assert meta["count"] == 3
    assert (index_dir / "vectors.npy").exists()

    retriever = ManualRetriever(index_dir=index_dir, embed=_fake_embed)
    assert retriever.available
    hits = retriever.search("renovacion de cafe", k=2)
    # El fragmento de café debe quedar primero.
    assert hits[0][0].page == 1
    assert "cafe" in hits[0][0].text.lower()


def test_contexto_incluye_cita_de_pagina(tmp_path, monkeypatch):
    monkeypatch.setattr(manual_index, "extract_pages", lambda _p: _fake_pages())
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-fake")
    index_dir = tmp_path / "idx"
    build_index(pdf_path=pdf, out_dir=index_dir, embed=_fake_embed)

    retriever = ManualRetriever(index_dir=index_dir, embed=_fake_embed)
    ctx = retriever.contexto("compra de ganado", k=1)
    assert "[Manual p.2]" in ctx
    assert "ganado" in ctx.lower()


def test_retriever_sin_indice_no_revienta(tmp_path):
    retriever = ManualRetriever(index_dir=tmp_path / "no_existe", embed=_fake_embed)
    assert not retriever.available
    assert retriever.search("lo que sea") == []
    assert retriever.contexto("lo que sea") == ""


# --- cableado en code_resolver --------------------------------------------


def _fake_catalogo() -> Catalogo:
    return Catalogo(
        entries=[
            CatalogoEntry(
                categoria_macro="1. Producción",
                cod_destino=141100,
                destino="Café",
                linea_credito="Inversión",
            )
        ]
    )


class _StubRetriever:
    """Retriever con índice 'cargado' que inyecta un marcador reconocible."""

    available = True

    def contexto(self, query: str, k: int = 5) -> str:
        return "[Manual p.7] el destino financia la renovacion de cafetales"


def test_code_resolver_inyecta_contexto_del_manual():
    capturado: dict[str, str] = {}

    def chat(messages: Sequence[BaseMessage], model: str) -> str:
        # Segundo call = paso 2 (elige destino): aquí debe ir el contexto.
        capturado["last"] = str(messages[-1].content)
        # Una sola categoría y un solo destino → índices 0.
        return json.dumps({"indice": 0, "confianza": "alta"})

    resolver = CodeResolver(
        catalogo=_fake_catalogo(), chat=chat, retriever=_StubRetriever()
    )
    result = resolver.resolve("Cultivo de café", destino="Renovación")

    assert result.cod_rubro == 141100
    assert "Manual de Servicios" in capturado["last"]
    assert "renovacion de cafetales" in capturado["last"]


def test_code_resolver_sin_manual_sigue_funcionando(tmp_path):
    def chat(messages: Sequence[BaseMessage], model: str) -> str:
        return json.dumps({"indice": 0, "confianza": "media"})

    sin_indice = ManualRetriever(index_dir=tmp_path / "vacio", embed=_fake_embed)
    resolver = CodeResolver(
        catalogo=_fake_catalogo(), chat=chat, retriever=sin_indice
    )
    result = resolver.resolve("café")
    assert result.cod_rubro == 141100  # degrada sin romper
