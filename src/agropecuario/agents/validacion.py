"""Agente 2 — Validación. Nodos LangGraph.

Dos nodos: `validar` aplica reglas, `notificar_remitente` envía la respuesta
pidiendo los campos faltantes (rama "no aprobado").
"""

from __future__ import annotations

from ..ingesta.gmail_client import GmailClient
from ..logging_conf import get_logger
from ..models import ProjectStatus
from ..validacion.gap_manager import build_result, draft_reply_for_gaps
from ..validacion.rule_engine import RuleSet
from ..validacion.validator import validate_fields
from .state import GraphState

logger = get_logger(__name__)


def make_validar_node(rules: RuleSet):
    def node(state: GraphState) -> GraphState:
        fields = state.get("fields", {})
        validations = validate_fields(fields, rules)
        result = build_result(validations, rules)
        logger.info(
            "agent.validacion.done",
            aprobado=result.aprobado,
            gaps=len(result.gaps),
        )
        status = ProjectStatus.APPROVED if result.aprobado else ProjectStatus.INCOMPLETE
        return {**state, "validation": result, "status": status.value}

    return node


def make_notificar_node(gmail: GmailClient):
    def node(state: GraphState) -> GraphState:
        email = state["email"]
        validation = state["validation"]
        body = draft_reply_for_gaps(validation)
        try:
            gmail.send_reply(
                thread_id=email.thread_id,
                to=email.sender,
                subject=f"Re: {email.subject}",
                body=body,
            )
            return {**state, "reply_sent": True}
        except NotImplementedError:
            logger.warning("agent.validacion.reply_not_implemented")
            return {**state, "reply_sent": False, "error": "reply_not_implemented"}

    return node


def route_after_validation(state: GraphState) -> str:
    """Condición del grafo: siguiente nodo según resultado."""
    return "generar" if state["validation"].aprobado else "notificar"
