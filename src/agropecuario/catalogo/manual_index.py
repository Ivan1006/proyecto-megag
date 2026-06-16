"""Construcción del índice RAG del Manual de Servicios Finagro.

El Manual de Servicios (PDF de varios MB) es la fuente que explica QUÉ financia
cada destino y qué producto/condiciones aplican. El catálogo (`loader.py`) solo
trae los nombres cortos; el manual aporta el contexto que el `code_resolver`
necesita para razonar "a qué se dedica la empresa → qué destino aplica".

Como el PDF no cabe en un prompt, se indexa una sola vez (offline):

    PDF → texto por página (pdfplumber) → chunks → embeddings → índice en disco

El índice vive en `config/manual_index/`:

| Archivo        | Contenido                                          |
|----------------|----------------------------------------------------|
| `vectors.npy`  | matriz NxD float32 con un embedding por chunk       |
| `chunks.json`  | lista de chunks (texto + página + índice)           |
| `meta.json`    | modelo de embedding, dimensión, conteo, fuente      |

`manual_retriever.py` consume este índice en runtime. La función de embedding se
inyecta (`embed`) para poder testear sin red ni API key.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from ..logging_conf import get_logger
from ..settings import get_settings

logger = get_logger(__name__)

# `embed(textos)` -> una lista de vectores (uno por texto). Inyectable para tests.
EmbedFn = Callable[[Sequence[str]], list[list[float]]]

# Parámetros de troceado. Editables si el manual cambia de densidad.
CHUNK_SIZE = 1000  # caracteres por chunk
CHUNK_OVERLAP = 150  # solape entre chunks contiguos

VECTORS_FILE = "vectors.npy"
CHUNKS_FILE = "chunks.json"
META_FILE = "meta.json"


class ManualChunk(BaseModel):
    """Un fragmento del manual con su procedencia (para citar la página)."""

    text: str
    page: int
    idx: int


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    """Trocea un texto en ventanas de ~`size` chars, cortando en espacios."""
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            corte = text.rfind(" ", start, end)
            if corte > start:
                end = corte
        fragmento = text[start:end].strip()
        if fragmento:
            chunks.append(fragmento)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    """Devuelve (nº de página 1-based, texto) por cada página con texto."""
    import pdfplumber

    paginas: list[tuple[int, str]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for n, page in enumerate(pdf.pages, start=1):
            texto = page.extract_text() or ""
            if texto.strip():
                paginas.append((n, texto))
    return paginas


def build_chunks(
    pdf_path: Path, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[ManualChunk]:
    """Extrae el PDF y lo trocea preservando el número de página."""
    chunks: list[ManualChunk] = []
    for page_no, texto in extract_pages(pdf_path):
        for fragmento in _split_text(texto, size, overlap):
            chunks.append(ManualChunk(text=fragmento, page=page_no, idx=len(chunks)))
    return chunks


def build_index(
    pdf_path: Path | None = None,
    out_dir: Path | None = None,
    embed: EmbedFn | None = None,
) -> dict[str, int | str]:
    """Construye y persiste el índice del manual. Devuelve metadatos del build."""
    settings = get_settings()
    pdf_path = pdf_path or settings.manual_pdf_path
    out_dir = out_dir or settings.manual_index_dir
    embed = embed or _default_embed

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"Manual no encontrado en {pdf_path}. Coloca el PDF ahí o define "
            "MANUAL_PDF_PATH antes de indexar."
        )

    chunks = build_chunks(pdf_path)
    if not chunks:
        raise ValueError(f"El PDF {pdf_path} no produjo texto indexable.")

    vectors = np.asarray(embed([c.text for c in chunks]), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
        raise ValueError(
            f"Embeddings inconsistentes: {vectors.shape} para {len(chunks)} chunks."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / VECTORS_FILE, vectors)
    (out_dir / CHUNKS_FILE).write_text(
        json.dumps([c.model_dump() for c in chunks], ensure_ascii=False),
        encoding="utf-8",
    )
    meta = {
        "model": settings.embedding_model,
        "dim": int(vectors.shape[1]),
        "count": len(chunks),
        "source": pdf_path.name,
    }
    (out_dir / META_FILE).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    logger.info("manual.indexado", **meta, out_dir=str(out_dir))
    return meta


def _default_embed(textos: Sequence[str]) -> list[list[float]]:
    """Embeddings reales contra OpenAI; se construye perezosamente."""
    from langchain_openai import OpenAIEmbeddings

    settings = get_settings()
    emb = OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
    return emb.embed_documents(list(textos))
