"""Match determinístico actividad → destino sobre los nombres del catálogo.

El Anexo Finagro (`catalogo_destinos.xlsx`) no trae una clave única (tipo CIIU)
para mapear una actividad a su código; el único enganche es el **nombre del
destino** ("Café", "Cría de porcinos", "Arroz riego"). Este módulo puntúa cada
destino por solapamiento de palabras (con raíces compartidas: `porcinos` ≈
`porcicultura`, `café` ≈ `cafetales`) contra el texto de la actividad + la razón
social del cliente.

El resultado es una **lista de candidatos ordenada**, no una decisión final: el
`code_resolver` la usa para (a) resolver sin LLM cuando un nombre queda cubierto
al 100% y (b) acotar el universo que ve el LLM cuando hay que desempatar.

Se excluyen las categorías que NO son actividades productivas (comisión FAG,
prima de seguro): son adiciones al crédito, no el destino de la sección 5, y eran
la causa de que el resolver eligiera `410003 Comisión Garantía FAG` a ciegas.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel

from .loader import CatalogoEntry

# Categorías del Anexo que no describen una actividad financiable concreta.
# Se excluyen de la resolución automática del código. Editable si el negocio
# decide diligenciar la comisión/seguro por esta vía.
CATEGORIAS_EXCLUIDAS: frozenset[str] = frozenset({"Todas las Actividades Financiables"})

# Longitud mínima de token a considerar (descarta "de", "el", ruido de 1-2 letras).
_MIN_TOKEN = 3
# Raíz compartida mínima para tratar dos tokens como equivalentes.
_MIN_PREFIJO = 5

# Palabras que no aportan a identificar la actividad: artículos/preposiciones,
# sufijos societarios y ruido financiero (operación del crédito, no la actividad).
# OJO: "renovación", "sostenimiento", "compra"… SÍ son palabras de destino y no
# se filtran.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "del", "las", "los", "una", "por", "con", "para", "sus",
        # sufijos societarios
        "sas", "ltda", "cia", "compania", "sociedad", "empresa",
        # ruido financiero (describe la operación, no la actividad)
        "credito", "creditos", "credi", "prestamo", "cartera", "sustitutiva",
        "agrocredito", "financiacion", "desembolso", "cupo", "linea",
    }
)


class Match(BaseModel):
    """Un destino candidato con su puntaje de solapamiento."""

    entry: CatalogoEntry
    hits: int  # tokens del NOMBRE cubiertos (equivalencia difusa: raíz compartida)
    total: int  # nº de tokens del nombre
    exact_hits: int  # tokens del nombre cubiertos por igualdad EXACTA (sin raíz difusa)

    @property
    def coverage(self) -> float:
        """Fracción del nombre cubierta (difusa). 1.0 = nombre cubierto entero."""
        return self.hits / self.total if self.total else 0.0

    @property
    def exact_full(self) -> bool:
        """`True` si TODOS los tokens del nombre se igualaron de forma exacta.

        Es la evidencia que habilita el short-circuit determinístico: evita que
        una raíz difusa (`agro`→`agroforestería`, `ceba`→`cebada`) dispare un
        match total espurio.
        """
        return self.total > 0 and self.exact_hits == self.total


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _tokens(text: str) -> list[str]:
    """Normaliza a tokens: minúsculas, sin acentos, sin stopwords ni ruido corto."""
    plano = _strip_accents((text or "").lower())
    crudos = re.split(r"[^a-z0-9]+", plano)
    return [t for t in crudos if len(t) >= _MIN_TOKEN and t not in _STOPWORDS]


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b, strict=False):
        if ca != cb:
            break
        n += 1
    return n


def _tokens_equivalentes(a: str, b: str) -> bool:
    """`True` si dos tokens comparten raíz suficiente (porcinos≈porcicultura, ganado≈ganadería).

    Solo igualdad exacta o raíz común de ≥5 caracteres. Un prefijo más corto
    (`agro`, `ceba`, `caf`) genera demasiados falsos positivos, así que no basta.
    """
    return a == b or _common_prefix(a, b) >= _MIN_PREFIJO


def match_destinos(query: str, entries: list[CatalogoEntry]) -> list[Match]:
    """Candidatos ordenados por cobertura del nombre (desc), luego hits, luego código."""
    qset = set(_tokens(query))
    if not qset:
        return []

    matches: list[Match] = []
    for entry in entries:
        ntoks = _tokens(entry.destino)
        if not ntoks:
            continue
        hits = sum(1 for nt in ntoks if any(_tokens_equivalentes(qt, nt) for qt in qset))
        if not hits:
            continue
        exact_hits = sum(1 for nt in ntoks if nt in qset)
        matches.append(Match(entry=entry, hits=hits, total=len(ntoks), exact_hits=exact_hits))

    matches.sort(key=lambda m: (-m.coverage, -m.hits, m.entry.cod_destino))
    return matches


def entries_resolubles(entries: list[CatalogoEntry]) -> list[CatalogoEntry]:
    """Destinos elegibles como actividad (excluye comisión FAG / prima seguro)."""
    return [e for e in entries if e.categoria_macro not in CATEGORIAS_EXCLUIDAS]
