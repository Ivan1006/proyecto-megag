"""Recuperación RAG sobre el índice del Manual de Servicios Finagro.

Carga el índice construido por `manual_index.py` y, dada la actividad descrita
en el correo, devuelve los fragmentos del manual más relevantes para que el
`code_resolver` razone qué destino financiar.

Búsqueda por coseno en memoria con numpy: para un manual de unos cientos de
chunks es instantáneo y evita un vector store con servidor. La función de
embedding se inyecta (`embed`) para testear sin red.

Si el índice no existe, `available` es `False` y `search()` devuelve `[]`: el
`code_resolver` degrada a su comportamiento previo y avisa que falta indexar.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..logging_conf import get_logger
from ..settings import get_settings
from .manual_index import (
    CHUNKS_FILE,
    META_FILE,
    VECTORS_FILE,
    EmbedFn,
    ManualChunk,
    _default_embed,
)

logger = get_logger(__name__)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """Normaliza filas a norma 1 (coseno = producto punto). Evita /0."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class ManualRetriever:
    """Busca fragmentos del manual relevantes a una consulta, por coseno."""

    def __init__(
        self,
        index_dir: Path | None = None,
        embed: EmbedFn | None = None,
    ) -> None:
        self.index_dir = index_dir or get_settings().manual_index_dir
        self._embed = embed or _default_embed
        self._vectors: np.ndarray | None = None
        self._chunks: list[ManualChunk] | None = None

    @property
    def available(self) -> bool:
        """`True` si los tres archivos del índice existen en disco."""
        return all(
            (self.index_dir / f).exists()
            for f in (VECTORS_FILE, CHUNKS_FILE, META_FILE)
        )

    def _load(self) -> None:
        if self._vectors is not None and self._chunks is not None:
            return
        vectors = np.load(self.index_dir / VECTORS_FILE).astype(np.float32)
        raw = json.loads((self.index_dir / CHUNKS_FILE).read_text(encoding="utf-8"))
        chunks = [ManualChunk(**c) for c in raw]
        if vectors.shape[0] != len(chunks):
            raise ValueError(
                f"Índice corrupto: {vectors.shape[0]} vectores vs {len(chunks)} chunks."
            )
        self._vectors = _normalize(vectors)
        self._chunks = chunks

    def search(self, query: str, k: int = 5) -> list[tuple[ManualChunk, float]]:
        """Top-`k` fragmentos por similitud coseno. `[]` si no hay índice."""
        if not query.strip() or not self.available:
            return []
        self._load()
        assert self._vectors is not None and self._chunks is not None

        q = np.asarray(self._embed([query]), dtype=np.float32)
        q = _normalize(q)[0]
        scores = self._vectors @ q
        k = min(k, len(self._chunks))
        top = np.argsort(-scores)[:k]
        return [(self._chunks[i], float(scores[i])) for i in top]

    def contexto(self, query: str, k: int = 5) -> str:
        """Bloque de texto con los fragmentos top-`k`, listo para el prompt."""
        hits = self.search(query, k)
        if not hits:
            return ""
        partes = [f"[Manual p.{c.page}] {c.text}" for c, _ in hits]
        return "\n\n".join(partes)


@lru_cache(maxsize=1)
def get_retriever() -> ManualRetriever:
    """Retriever cacheado con embeddings reales (un índice por proceso)."""
    return ManualRetriever()
