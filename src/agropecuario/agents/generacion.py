"""Agente 3 — Generación. Nodo LangGraph (flujo Finagro).

Consolida los campos extraídos (defaults + códigos de la sección 5 vía
`code_resolver` + cronograma) con el `enricher` y renderiza los entregables
oficiales Bancolombia/Finagro: Excel rellenado celda a celda y su PDF, que
quedan en `data/output/<message_id>/`.

La entrega de los entregables está **sin definir** (será por correo o a una ruta
de un NAS); hasta entonces la única copia vive en el disco de la máquina que los
generó. Ver [[Tareas pendientes]] del vault.
"""

from __future__ import annotations

from pathlib import Path

from ..generacion.enricher import enrich_fields
from ..generacion.excel_writer import render_excel
from ..generacion.pdf_writer import render_pdf
from ..logging_conf import get_logger
from ..models import GeneratedOutputs, ProjectStatus
from ..settings import get_settings
from .state import GraphState

logger = get_logger(__name__)


def make_generacion_node():
    settings = get_settings()

    def node(state: GraphState) -> GraphState:
        fields = enrich_fields(state.get("fields", {}))

        base = settings.output_dir / state["message_id"]
        excel_path = render_excel(fields, base / "solicitud_credito.xlsx")
        pdf_path: Path | None
        try:
            pdf_path = render_pdf(excel_path, base / "solicitud_credito.pdf")
        except Exception as e:  # noqa: BLE001
            logger.warning("agent.generacion.pdf_failed", error=str(e))
            pdf_path = None
        logger.info("agent.generacion.rendered", pdf=str(pdf_path), xlsx=str(excel_path))

        outputs = GeneratedOutputs(pdf_path=pdf_path, excel_path=excel_path)

        return {
            **state,
            "outputs": outputs,
            "status": ProjectStatus.GENERATED.value,
        }

    return node
