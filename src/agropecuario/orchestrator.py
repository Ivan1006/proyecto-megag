"""Orquestador LangGraph: une los 3 agentes en un StateGraph.

Flujo:
    START → ingesta → validar → [aprobado?] → generar → END
                              └→ notificar → END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .agents.generacion import make_generacion_node
from .agents.ingesta import make_ingesta_node
from .agents.state import GraphState
from .agents.validacion import (
    make_notificar_node,
    make_validar_node,
    route_after_validation,
)
from .generacion.template_engine import load_template
from .ingesta.gmail_client import GmailClient
from .settings import get_settings
from .storage.drive_client import DriveClient
from .validacion.rule_engine import load_rules


def build_graph(enable_drive: bool = True):
    settings = get_settings()
    settings.ensure_dirs()

    rules = load_rules(settings.rules_path)
    template = load_template(settings.template_path)
    gmail = GmailClient()
    drive = DriveClient(gmail=gmail) if enable_drive and settings.drive_output_folder_id else None

    graph: StateGraph = StateGraph(GraphState)
    graph.add_node("ingesta", make_ingesta_node(gmail, rules))
    graph.add_node("validar", make_validar_node(rules))
    graph.add_node("generar", make_generacion_node(template, drive))
    graph.add_node("notificar", make_notificar_node(gmail))

    graph.add_edge(START, "ingesta")
    graph.add_edge("ingesta", "validar")
    graph.add_conditional_edges(
        "validar",
        route_after_validation,
        {"generar": "generar", "notificar": "notificar"},
    )
    graph.add_edge("generar", END)
    graph.add_edge("notificar", END)

    return graph.compile()


def run_for_message(message_id: str, enable_drive: bool = True) -> GraphState:
    app = build_graph(enable_drive=enable_drive)
    initial: GraphState = {"message_id": message_id, "status": "pending"}
    return app.invoke(initial)
