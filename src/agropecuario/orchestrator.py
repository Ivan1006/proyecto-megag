"""Orquestador LangGraph: une los 3 agentes en un StateGraph.

Flujo:
    START → ingesta → validar → [aprobado?] → generar → END
                              └→ notificar → END

Los entregables terminan en disco (`data/output/`). No hay paso de subida: Google
Drive se descartó (2026-08-29) y la entrega definitiva —correo o NAS— está sin
definir.
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
from .ingesta.gmail_client import GmailClient
from .settings import get_settings
from .validacion.rule_engine import load_rules


def build_graph():
    settings = get_settings()
    settings.ensure_dirs()

    rules = load_rules(settings.rules_path)
    gmail = GmailClient()

    graph: StateGraph = StateGraph(GraphState)
    graph.add_node("ingesta", make_ingesta_node(gmail, rules))
    graph.add_node("validar", make_validar_node(rules))
    graph.add_node("generar", make_generacion_node())
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


def run_for_message(message_id: str) -> GraphState:
    app = build_graph()
    initial: GraphState = {"message_id": message_id, "status": "pending"}
    return app.invoke(initial)
