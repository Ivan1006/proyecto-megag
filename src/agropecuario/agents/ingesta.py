"""Agente 1 — Ingesta. Nodo LangGraph.

Recibe un `message_id`, descarga el correo con sus adjuntos, extrae el texto
y mapea (LLM) a los campos definidos en rules.yaml.
"""

from __future__ import annotations

from ..generacion.mapper import map_content_to_fields
from ..ingesta.extractor import extract
from ..ingesta.gmail_client import GmailClient
from ..logging_conf import get_logger
from ..models import ProjectStatus
from ..validacion.rule_engine import RuleSet
from .state import GraphState

logger = get_logger(__name__)


def make_ingesta_node(gmail: GmailClient, rules: RuleSet):
    def node(state: GraphState) -> GraphState:
        message_id = state["message_id"]
        logger.info("agent.ingesta.start", message_id=message_id)

        email = gmail.fetch_message(message_id)
        extracted = extract(email)

        # Enriquecer con mapeo LLM en un solo paso.
        extracted.fields_raw = map_content_to_fields(extracted.combined_text, rules)

        return {
            **state,
            "email": email,
            "extracted": extracted,
            "fields": extracted.fields_raw,
            "status": ProjectStatus.EXTRACTED.value,
        }

    return node
