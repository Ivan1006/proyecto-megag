"""Sub-agente `code_resolver`: infiere los códigos Finagro de la sección 5.

El correo describe la actividad del cliente y el destino del crédito en lenguaje
natural ("renovación de café", "compra de novillos de ceba"), pero el formulario
exige los códigos exactos del Anexo Finagro. Este sub-agente cierra esa brecha.

Estrategia de 2 pasos LLM (ver [[Decisiones tecnicas]] del vault):

1. **Acotar por categoría macro** (Producción / Transformación / Comercialización
   / Multiactividad / Ambientales / Todas). Reduce ~260 destinos a unas decenas.
2. **Elegir el destino específico** dentro del subconjunto filtrado.

Esto evita saturar el contexto con todo el catálogo en una sola llamada y reduce
costo + tasa de error.

El LLM se inyecta vía el parámetro `chat` para poder testear sin red ni API key:
`chat(messages, model) -> str` debe devolver el contenido (idealmente JSON).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from ..logging_conf import get_logger
from ..settings import get_settings
from .loader import Catalogo, CatalogoEntry, get_catalogo
from .manual_retriever import ManualRetriever, get_retriever
from .matcher import entries_resolubles, match_destinos

logger = get_logger(__name__)

# Cuántos fragmentos del Manual de Servicios se inyectan como contexto al elegir
# el destino. Editable si los prompts crecen demasiado.
MANUAL_TOP_K = 5

# Máximo de candidatos del match determinístico que se pasan al LLM para desempatar.
MAX_SHORTLIST = 12

# `chat(messages, model)` -> texto de la respuesta. Inyectable para tests.
ChatFn = Callable[[Sequence[BaseMessage], str], str]

# Mapeo nombre de línea de crédito Finagro → código de línea de la sección 5.
# El Anexo solo trae el nombre ("Inversión" / "Capital de trabajo"); el formulario
# pide un código numérico. Editable si Finagro recodifica las líneas.
LINEAS_CREDITO_CODIGO: dict[str, int] = {
    "inversión": 2,
    "inversion": 2,
    "capital de trabajo": 1,
}

_SYSTEM = (
    "Eres un analista de crédito agropecuario experto en el Anexo de Destinos "
    "Finagro. Tu tarea es asignar el código de destino correcto a la actividad "
    "que describe el cliente. Respondes SIEMPRE con un único JSON válido, sin "
    "texto adicional."
)


class ResolverResult(BaseModel):
    """Códigos resueltos, listos para una fila de la tabla de la sección 5.

    Los campos financieros (unidades, valores, plazo en meses, gracia, DTF) NO
    los produce el resolver: vienen del correo vía el `mapper`. Aquí solo van los
    códigos y descripciones que se infieren del catálogo.
    """

    cod_linea: int | None = None
    cod_rubro: int
    descripcion_rubro: str
    producto_relacionado: str | None = None
    plazo_dias: int | None = None
    linea_credito: str | None = None
    categoria_macro: str
    confianza: str = "media"  # alta | media | baja
    metodo: str = "llm"  # catalogo (determinístico) | llm (desempate) | fallback

    def to_actividad(self) -> dict[str, Any]:
        """Sub-dict de códigos para fusionar con los campos financieros."""
        return {
            "cod_linea": self.cod_linea,
            "cod_rubro": self.cod_rubro,
            "descripcion_rubro": self.descripcion_rubro,
        }


class CodeResolver:
    """Resuelve códigos Finagro consultando el catálogo con 2 pasos LLM."""

    def __init__(
        self,
        catalogo: Catalogo | None = None,
        chat: ChatFn | None = None,
        line_codes: dict[str, int] | None = None,
        retriever: ManualRetriever | None = None,
    ) -> None:
        self.catalogo = catalogo or get_catalogo()
        self._chat = chat or _default_chat
        self.line_codes = line_codes or LINEAS_CREDITO_CODIGO
        self.retriever = retriever or get_retriever()

    # --- API pública -------------------------------------------------------

    def resolve(
        self,
        actividad: str,
        destino: str | None = None,
        contexto_web: str | None = None,
        beneficiario: str | None = None,
    ) -> ResolverResult:
        """Resuelve el destino Finagro para una actividad descrita en texto.

        `actividad` es la actividad económica del cliente (p. ej. "cultivo de
        café"); `destino` es el uso del crédito si se conoce ("renovación de
        cafetales"). El segundo afina la elección dentro de la categoría.

        `beneficiario` (razón social) se usa como señal fuerte del giro real del
        cliente en el match determinístico (p. ej. "PORCICULTORES APA" → porcinos).

        `contexto_web` es un resumen (opcional) de la actividad de la empresa
        obtenido de una búsqueda web; sirve de apoyo al LLM cuando el correo es
        pobre. El correo SIEMPRE manda: la web solo desempata.

        Estrategia (ver [[Tareas pendientes]] T5): el código sale del Anexo por
        **match determinístico** sobre los nombres de destino; el LLM solo
        desempata entre los candidatos o resuelve cuando no hay ninguno. Las
        categorías no productivas (comisión FAG, prima seguro) quedan excluidas.
        """
        query_llm = actividad if not destino else f"{actividad}. Destino del crédito: {destino}"
        query_match = " ".join(x for x in (actividad, destino, beneficiario) if x)

        resolubles = entries_resolubles(self.catalogo.entries)
        matches = match_destinos(query_match, resolubles)

        # (a) Determinístico: un nombre del catálogo queda cubierto por completo
        #     con igualdad EXACTA y de forma única → se usa ese código sin LLM.
        completos = [m for m in matches if m.exact_full]
        if len(completos) == 1:
            entry = completos[0].entry
            logger.info(
                "code_resolver.match_deterministico",
                cod_rubro=entry.cod_destino,
                destino=entry.destino,
                actividad=actividad,
            )
            return self._build_result(entry, entry.categoria_macro, "alta", metodo="catalogo")

        # (b) Hay candidatos por palabra clave → el LLM desempata SOLO entre ellos.
        if matches:
            shortlist = [m.entry for m in matches[:MAX_SHORTLIST]]
            entry, confianza = self._pick_destino(
                query_llm, shortlist, contexto_web, beneficiario
            )
            return self._build_result(entry, entry.categoria_macro, confianza, metodo="llm")

        # (c) Sin candidatos → 2 pasos LLM sobre el catálogo resoluble.
        return self._resolve_llm_2pasos(query_llm, resolubles, contexto_web, beneficiario)

    # --- pasos LLM ---------------------------------------------------------

    def _resolve_llm_2pasos(
        self,
        query: str,
        resolubles: list[CatalogoEntry],
        contexto_web: str | None,
        beneficiario: str | None = None,
    ) -> ResolverResult:
        """Fallback: acota por categoría macro y elige destino, ambos vía LLM."""
        categoria = self._pick_categoria(query, resolubles, beneficiario)
        subset = [e for e in resolubles if e.categoria_macro == categoria]
        if not subset:
            logger.warning("code_resolver.categoria_vacia", categoria=categoria)
            subset = resolubles  # fallback: todo el catálogo resoluble
        entry, confianza = self._pick_destino(query, subset, contexto_web, beneficiario)
        return self._build_result(entry, entry.categoria_macro, confianza, metodo="fallback")

    def _bloque_cliente(self, beneficiario: str | None) -> str:
        """Razón social como indicio FUERTE del giro real (clave si el correo es pobre)."""
        if not beneficiario:
            return ""
        return (
            f"Razón social del cliente: {beneficiario}\n"
            "El nombre del cliente suele delatar su actividad real (p. ej. "
            "'PORCICULTORES ...' → porcinos, 'AVÍCOLA ...' → aves). Priorízalo por "
            "encima de palabras genéricas de la operación de crédito como "
            "'renovación', 'cartera' o 'sustitutiva', que NO indican el rubro.\n\n"
        )

    def _pick_categoria(
        self, query: str, entries: list[CatalogoEntry], beneficiario: str | None = None
    ) -> str:
        categorias: list[str] = []
        for e in entries:
            if e.categoria_macro not in categorias:
                categorias.append(e.categoria_macro)
        if len(categorias) <= 1:
            return categorias[0] if categorias else ""

        opciones = "\n".join(f"{i}. {c}" for i, c in enumerate(categorias))
        messages = [
            SystemMessage(content=_SYSTEM),
            HumanMessage(
                content=(
                    "Paso 1 de 2 — clasifica la actividad en UNA categoría macro.\n\n"
                    f"{self._bloque_cliente(beneficiario)}"
                    f"Actividad del cliente (según el correo):\n{query}\n\n"
                    f"Categorías disponibles:\n{opciones}\n\n"
                    'Responde JSON: {"indice": <número de la categoría>}'
                )
            ),
        ]
        data = self._invoke_json(messages, get_settings().openai_model_mini)
        idx = data.get("indice")
        if isinstance(idx, int) and 0 <= idx < len(categorias):
            return categorias[idx]
        logger.warning("code_resolver.categoria_invalida", raw=data)
        return categorias[0]

    def _pick_destino(
        self,
        query: str,
        subset: list[CatalogoEntry],
        contexto_web: str | None = None,
        beneficiario: str | None = None,
    ) -> tuple[CatalogoEntry, str]:
        catalogo_txt = "\n".join(f"{i}. {e.resumen()}" for i, e in enumerate(subset))
        contexto = self._manual_contexto(query)
        bloque_manual = (
            f"Contexto del Manual de Servicios Finagro (úsalo para entender qué "
            f"financia cada destino):\n{contexto}\n\n"
            if contexto
            else ""
        )
        bloque_web = (
            f"Contexto externo sobre la empresa (búsqueda web de su razón social; "
            f"úsalo solo como apoyo, el correo SIEMPRE manda):\n{contexto_web}\n\n"
            if contexto_web
            else ""
        )
        messages = [
            SystemMessage(content=_SYSTEM),
            HumanMessage(
                content=(
                    "Paso 2 de 2 — elige el destino de crédito que mejor encaja.\n\n"
                    f"{self._bloque_cliente(beneficiario)}"
                    f"Actividad del cliente (según el correo):\n{query}\n\n"
                    f"{bloque_manual}"
                    f"{bloque_web}"
                    f"Destinos candidatos:\n{catalogo_txt}\n\n"
                    "Elige el índice del destino más específico y correcto, coherente "
                    "con la actividad real del cliente. Indica tu confianza "
                    '("alta", "media" o "baja").\n'
                    'Responde JSON: {"indice": <número>, "confianza": "<nivel>"}'
                )
            ),
        ]
        data = self._invoke_json(messages, get_settings().openai_model)
        idx = data.get("indice")
        confianza = str(data.get("confianza", "media")).lower()
        if confianza not in {"alta", "media", "baja"}:
            confianza = "media"
        if isinstance(idx, int) and 0 <= idx < len(subset):
            return subset[idx], confianza
        logger.warning("code_resolver.destino_invalido", raw=data, n=len(subset))
        return subset[0], "baja"

    # --- helpers -----------------------------------------------------------

    def _manual_contexto(self, query: str) -> str:
        """Fragmentos del manual relevantes; "" si no está indexado (con aviso)."""
        if not self.retriever.available:
            logger.warning(
                "code_resolver.manual_no_indexado",
                hint="Ejecuta `agropecuario manual-index` para cargar el manual.",
            )
            return ""
        return self.retriever.contexto(query, k=MANUAL_TOP_K)

    def _build_result(
        self, entry: CatalogoEntry, categoria: str, confianza: str, metodo: str = "llm"
    ) -> ResolverResult:
        cod_linea = None
        if entry.linea_credito:
            cod_linea = self.line_codes.get(entry.linea_credito.lower())
        return ResolverResult(
            cod_linea=cod_linea,
            cod_rubro=entry.cod_destino,
            descripcion_rubro=entry.destino,
            producto_relacionado=entry.producto_relacionado,
            plazo_dias=entry.plazo_dias,
            linea_credito=entry.linea_credito,
            categoria_macro=categoria,
            confianza=confianza,
            metodo=metodo,
        )

    def _invoke_json(self, messages: Sequence[BaseMessage], model: str) -> dict[str, Any]:
        raw = self._chat(messages, model)
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            logger.warning("code_resolver.json_invalido", raw=str(raw)[:300])
            return {}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _default_chat(messages: Sequence[BaseMessage], model: str) -> str:
    """Implementación real contra OpenAI; se construye perezosamente."""
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    llm = ChatOpenAI(
        model=model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).bind(response_format={"type": "json_object"})
    response = llm.invoke(list(messages))
    return response.content if isinstance(response.content, str) else str(response.content)
