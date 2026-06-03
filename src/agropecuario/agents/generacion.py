"""Agente 3 — Generación. Nodo LangGraph.

Construye el `ProjectData`, calcula campos derivados, genera secciones con LLM
y renderiza los entregables PDF + Excel. Opcionalmente los sube a Drive.
"""

from __future__ import annotations

from pathlib import Path

from ..generacion.enricher import compute_calculated, generate_llm_sections
from ..generacion.excel_writer import render_excel
from ..generacion.pdf_writer import render_pdf
from ..generacion.template_engine import Template
from ..logging_conf import get_logger
from ..models import GeneratedOutputs, ProjectData, ProjectStatus
from ..settings import get_settings
from ..storage.drive_client import DriveClient
from .state import GraphState

logger = get_logger(__name__)


def make_generacion_node(template: Template, drive: DriveClient | None = None):
    settings = get_settings()

    def node(state: GraphState) -> GraphState:
        fields = state["fields"]
        known_keys = {
            "productor_nombre", "productor_documento", "predio_nombre",
            "ubicacion_municipio", "ubicacion_departamento",
            "cultivo", "predio_hectareas", "monto_solicitado",
        }
        opcionales = {k: v for k, v in fields.items() if k not in known_keys and v is not None}

        project = ProjectData(
            productor_nombre=str(fields.get("productor_nombre", "")),
            productor_documento=str(fields.get("productor_documento", "")),
            predio_nombre=str(fields.get("predio_nombre", "")),
            ubicacion_municipio=str(fields.get("ubicacion_municipio", "")),
            ubicacion_departamento=str(fields.get("ubicacion_departamento", "")),
            cultivo=str(fields.get("cultivo", "")),
            predio_hectareas=float(fields.get("predio_hectareas", 0)),
            monto_solicitado=float(fields.get("monto_solicitado", 0)),
            campos_opcionales=opcionales,
            fuente_email_id=state["message_id"],
        )
        project.calculados = compute_calculated(fields, template)
        project.secciones_generadas = generate_llm_sections(fields, template)

        base = settings.output_dir / state["message_id"]
        pdf_path = render_pdf(project, template, base / "proyecto.pdf")
        excel_path = render_excel(project, template, base / "proyecto.xlsx")
        logger.info("agent.generacion.rendered", pdf=str(pdf_path), xlsx=str(excel_path))

        outputs = GeneratedOutputs(pdf_path=pdf_path, excel_path=excel_path)

        if drive is not None:
            try:
                outputs.drive_pdf_url = drive.upload(pdf_path)
                outputs.drive_excel_url = drive.upload(excel_path)
            except Exception as e:  # noqa: BLE001
                logger.warning("agent.generacion.drive_upload_failed", error=str(e))

        return {
            **state,
            "project": project,
            "outputs": outputs,
            "status": ProjectStatus.GENERATED.value,
        }

    return node
