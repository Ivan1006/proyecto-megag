"""Agente 3 — Generación. Nodo LangGraph (flujo Finagro).

Consolida los campos extraídos (defaults + códigos de la sección 5 vía
`code_resolver` + cronograma) con el `enricher` y renderiza los entregables
oficiales Bancolombia/Finagro: Excel rellenado celda a celda y su PDF.
Opcionalmente los sube a Drive.
"""

from __future__ import annotations

from pathlib import Path

from ..generacion.enricher import enrich_fields
from ..generacion.excel_writer import render_excel
from ..generacion.pdf_writer import render_pdf
from ..logging_conf import get_logger
from ..models import GeneratedOutputs, ProjectStatus
from ..settings import get_settings
from ..storage.drive_client import DriveClient
from .state import GraphState

logger = get_logger(__name__)


def make_generacion_node(drive: DriveClient | None = None):
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

        if drive is not None:
            try:
                if pdf_path is not None:
                    outputs.drive_pdf_url = drive.upload(pdf_path)
                outputs.drive_excel_url = drive.upload(excel_path)
            except Exception as e:  # noqa: BLE001
                logger.warning("agent.generacion.drive_upload_failed", error=str(e))

        return {
            **state,
            "outputs": outputs,
            "status": ProjectStatus.GENERATED.value,
        }

    return node
