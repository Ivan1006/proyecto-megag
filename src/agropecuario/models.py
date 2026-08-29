"""Contratos de datos compartidos entre agentes.

Cada agente recibe y devuelve instancias Pydantic: evita pasar dicts "sueltos"
entre nodos de LangGraph y garantiza validación en los bordes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class ProjectStatus(StrEnum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    INCOMPLETE = "incomplete"
    APPROVED = "approved"
    GENERATED = "generated"
    DELIVERED = "delivered"
    FAILED = "failed"


class Attachment(BaseModel):
    filename: str
    mime_type: str
    size_bytes: int
    local_path: Path
    extracted_text: str | None = None
    extracted_tables: list[list[list[Any]]] = Field(default_factory=list)


class EmailMessage(BaseModel):
    """Correo tal como llega desde Gmail."""

    message_id: str
    thread_id: str
    sender: EmailStr
    sender_name: str | None = None
    recipients: list[EmailStr] = Field(default_factory=list)
    subject: str
    received_at: datetime
    body_plain: str = ""
    body_html: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)


class EmailThread(BaseModel):
    """Conjunto de mensajes que pertenecen al mismo hilo de Gmail.

    Es la unidad de trabajo real del agente: una solicitud puede llegar
    repartida en varios correos (información inicial + correcciones + adjuntos
    extras). El analista marca el hilo con la etiqueta `bot` para disparar
    el procesamiento.
    """

    thread_id: str
    messages: list[EmailMessage] = Field(default_factory=list)
    triggered_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def last_message_id(self) -> str | None:
        return self.messages[-1].message_id if self.messages else None

    @property
    def last_activity_at(self) -> datetime | None:
        return self.messages[-1].received_at if self.messages else None

    @property
    def subject(self) -> str:
        return self.messages[0].subject if self.messages else ""

    @property
    def primary_sender(self) -> str:
        return self.messages[0].sender if self.messages else ""


class ExtractedContent(BaseModel):
    """Resultado del Agente 1 tras normalizar cuerpo y adjuntos."""

    email: EmailMessage
    combined_text: str
    fields_raw: dict[str, Any] = Field(default_factory=dict)
    # Si la extracción vino de un hilo, guardamos los mensajes que contribuyeron.
    thread_id: str | None = None
    contributing_message_ids: list[str] = Field(default_factory=list)


class FieldValidation(BaseModel):
    field_id: str
    present: bool
    value: Any | None = None
    severity: Literal["ok", "warning", "error"] = "ok"
    message: str | None = None


class Gap(BaseModel):
    """Representa un campo faltante o inconsistente."""

    field_id: str
    descripcion: str
    tipo: Literal["faltante", "fuera_de_rango", "formato_invalido", "inconsistencia"]
    sugerencia: str | None = None


class ValidationResult(BaseModel):
    campos: list[FieldValidation]
    gaps: list[Gap]
    completitud_requeridos: float = Field(ge=0.0, le=1.0)
    completitud_opcionales: float = Field(ge=0.0, le=1.0)
    aprobado: bool
    mensaje_resumen: str | None = None


class CalculatedField(BaseModel):
    field_id: str
    valor: Any
    formula: str | None = None


class ProjectData(BaseModel):
    """Datos listos para renderizado (Agente 3)."""

    productor_nombre: str
    productor_documento: str
    predio_nombre: str
    ubicacion_municipio: str
    ubicacion_departamento: str
    cultivo: str
    predio_hectareas: float
    monto_solicitado: float
    campos_opcionales: dict[str, Any] = Field(default_factory=dict)
    calculados: list[CalculatedField] = Field(default_factory=list)
    secciones_generadas: dict[str, str] = Field(default_factory=dict)
    fuente_email_id: str


class GeneratedOutputs(BaseModel):
    pdf_path: Path | None = None
    excel_path: Path | None = None
    drive_pdf_url: str | None = None
    drive_excel_url: str | None = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectRecord(BaseModel):
    """Registro persistido en SQLite; representa un proyecto en cualquier etapa."""

    id: str
    message_id: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    extracted: ExtractedContent | None = None
    validation: ValidationResult | None = None
    project: ProjectData | None = None
    outputs: GeneratedOutputs | None = None
    error: str | None = None
