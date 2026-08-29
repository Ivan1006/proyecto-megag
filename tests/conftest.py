"""Guardarraíles de la suite: ningún test toca la red.

Todos los puntos de salida a internet del proyecto (chat LLM, embeddings,
búsqueda web) están diseñados como dependencias inyectables — el test pasa su
doble y no se llama a OpenAI. El problema es que **olvidar la inyección no se
nota**: si hay `OPENAI_API_KEY` real en el entorno la llamada tiene éxito y el
test pasa igual, gastando API y volviéndose no determinista. Solo revienta en
CI, donde la llave es falsa.

Eso fue exactamente lo que pasó con `test_catalogo.py`: inyectaba el `chat`
falso pero no el `retriever`, así que el `code_resolver` embebía la consulta
del Manual contra OpenAI de verdad en cada corrida local.

Este módulo cierra el hueco desde los dos lados:

1. `_sin_red` sustituye cada implementación real por una que **falla con un
   mensaje explícito**. Un test que se salte la inyección ya no llama a la red:
   se cae diciendo qué doble le falta.
2. `_retriever_sin_indice` hace que el retriever por defecto del
   `code_resolver` no tenga índice, de modo que degrada a "sin contexto del
   manual" (su comportamiento documentado) en vez de intentar embeber. Un test
   que sí quiera probar el RAG inyecta su propio retriever y este default no le
   estorba.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agropecuario.catalogo.manual_retriever import ManualRetriever

# Cada entrada es (módulo, atributo) de una implementación que sale a internet.
_SALIDAS_DE_RED: tuple[tuple[str, str], ...] = (
    ("agropecuario.catalogo.code_resolver", "_default_chat"),
    ("agropecuario.generacion.mapper", "_default_chat"),
    ("agropecuario.catalogo.manual_index", "_default_embed"),
    ("agropecuario.catalogo.manual_retriever", "_default_embed"),
    ("agropecuario.investigacion.web_lookup", "_default_search"),
)


def _prohibir(modulo: str, atributo: str):
    def _fallar(*args: Any, **kwargs: Any):
        raise AssertionError(
            f"{modulo}.{atributo} se llamó de verdad durante un test. "
            "Inyecta el doble correspondiente (chat=, embed=, search= o "
            "retriever=) en vez de salir a la red."
        )

    return _fallar


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Convierte cualquier llamada real a la API en un fallo con explicación."""
    for modulo, atributo in _SALIDAS_DE_RED:
        monkeypatch.setattr(f"{modulo}.{atributo}", _prohibir(modulo, atributo))


@pytest.fixture(autouse=True)
def _retriever_sin_indice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """El retriever por defecto del resolver degrada en vez de embeber."""
    vacio = ManualRetriever(index_dir=tmp_path / "sin_indice")
    monkeypatch.setattr(
        "agropecuario.catalogo.code_resolver.get_retriever", lambda: vacio
    )
