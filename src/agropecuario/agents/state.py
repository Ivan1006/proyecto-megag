"""Estado compartido del grafo LangGraph."""

from __future__ import annotations

from typing import Any, TypedDict

from ..models import (
    EmailMessage,
    ExtractedContent,
    GeneratedOutputs,
    ProjectData,
    ValidationResult,
)


class GraphState(TypedDict, total=False):
    message_id: str
    status: str

    email: EmailMessage
    extracted: ExtractedContent
    fields: dict[str, Any]

    validation: ValidationResult
    reply_sent: bool

    project: ProjectData
    outputs: GeneratedOutputs

    error: str | None
