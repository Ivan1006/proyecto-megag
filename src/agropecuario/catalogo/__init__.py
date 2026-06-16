"""Catálogo de destinos de crédito Finagro y sub-agente `code_resolver`.

`loader.py` carga el Anexo Finagro (`config/catalogo_destinos.xlsx`) en una
estructura indexable; `code_resolver.py` infiere los códigos de la sección 5 del
formulario a partir de la actividad/destino descritos en el correo.
"""

from .code_resolver import CodeResolver, ResolverResult
from .loader import Catalogo, CatalogoEntry, load_catalogo
from .manual_index import ManualChunk, build_index
from .manual_retriever import ManualRetriever, get_retriever

__all__ = [
    "Catalogo",
    "CatalogoEntry",
    "load_catalogo",
    "CodeResolver",
    "ResolverResult",
    "ManualChunk",
    "build_index",
    "ManualRetriever",
    "get_retriever",
]
