"""Procesamiento end-to-end de un hilo Gmail.

Unifica la lógica para que la usen el CLI (`process-thread`, `watch-bot`)
y el endpoint HTTP del dashboard (`/threads/{id}/reprocess`).

Pasos:
    1. Descargar el hilo entero desde Gmail.
    2. Agregar (combinar bodies + deduplicar adjuntos).
    3. Persistir el run en SQLite (estado 'pending').
    4. Parsear adjuntos + (si hay OPENAI_API_KEY) llamar al mapper LLM.
    5. Validar contra reglas.
    6. Renderizar Excel + PDF si se aprueba.
    7. Etiquetar el hilo como procesado.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .ingesta.aggregator import aggregate_thread
from .ingesta.extractor import extract
from .ingesta.gmail_client import GmailClient
from .logging_conf import get_logger
from .models import EmailThread
from .settings import get_settings
from .storage import db

logger = get_logger(__name__)


def _preview(text: str, n: int = 400) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def process_thread(
    thread_id: str,
    gmail: GmailClient | None = None,
    *,
    use_llm: bool = True,
    render: bool = True,
    mark_done: bool = True,
) -> int:
    """Procesa un hilo y devuelve el `run_id` creado en SQLite."""
    settings = get_settings()
    settings.ensure_dirs()
    db.init_db()

    gmail = gmail or GmailClient()
    gmail.authenticate(interactive=False)

    logger.info("runner.fetch_thread", thread_id=thread_id)
    messages = gmail.fetch_thread(thread_id)
    if not messages:
        raise ValueError(f"El hilo {thread_id} no tiene mensajes")

    thread = EmailThread(thread_id=thread_id, messages=messages)
    virtual, contributing = aggregate_thread(thread)

    run_id = db.create_run(
        thread_id=thread_id,
        last_message_id=thread.last_message_id or "",
        subject=thread.subject,
        sender=thread.primary_sender,
        sender_name=messages[0].sender_name or "",
        received_at=thread.last_activity_at,
    )

    db.save_messages(
        run_id,
        [
            {
                "message_id": m.message_id,
                "sender": m.sender,
                "sender_name": m.sender_name,
                "subject": m.subject,
                "received_at": m.received_at.isoformat(),
                "body_preview": _preview(m.body_plain),
                "attachments": [a.filename for a in m.attachments],
            }
            for m in messages
        ],
    )

    try:
        db.update_run(run_id, status="extracted")
        extracted = extract(virtual)

        fields: dict[str, Any] = {}
        aprobado = True
        contexto_web: str | None = None
        if use_llm and settings.openai_api_key:
            from .generacion.mapper import map_content_to_fields
            from .validacion.rule_engine import load_rules

            rules = load_rules(settings.rules_path)
            fields = map_content_to_fields(extracted.combined_text, rules)
            db.update_run(run_id, fields_json=fields)

            from .validacion.gap_manager import build_result
            from .validacion.validator import validate_fields

            validations = validate_fields(fields, rules)
            result = build_result(validations, rules)
            db.update_run(
                run_id,
                completitud_req=result.completitud_requeridos,
                completitud_opt=result.completitud_opcionales,
                aprobado=result.aprobado,
            )
            db.save_gaps(
                run_id,
                [
                    {
                        "field_id": g.field_id,
                        "tipo": g.tipo,
                        "descripcion": g.descripcion,
                        "sugerencia": g.sugerencia,
                    }
                    for g in result.gaps
                ],
            )
            aprobado = result.aprobado
            if not aprobado:
                db.update_run(run_id, status="incomplete")

            # Investigación web de la razón social: apoya al resolver, deja un
            # flag de discrepancia y alimenta la justificación. El correo manda.
            findings = _investigar_web(run_id, fields)
            if findings and findings.found:
                contexto_web = findings.resumen
            _maybe_generar_justificacion(run_id, fields, findings)

        # Genera el Excel + PDF aunque el formulario esté incompleto: se rellenan
        # con los datos disponibles (las celdas sin dato quedan en blanco). El
        # estado final sigue reflejando la incompletitud.
        if render and fields:
            paths = _render_outputs(fields, thread_id, contexto_web=contexto_web)
            db.update_run(
                run_id,
                excel_path=str(paths["excel"]),
                pdf_path=str(paths["pdf"]) if paths.get("pdf") else None,
            )

        final_status = "incomplete" if not aprobado else ("generated" if fields else "extracted")
        _finish_and_tag(gmail, thread_id, run_id, final_status, mark_done)
        return run_id

    except Exception as e:  # noqa: BLE001
        logger.error("runner.failed", thread_id=thread_id, error=str(e))
        db.finish_run(run_id, status="failed", error=str(e))
        return run_id


def _investigar_web(run_id: int, fields: dict[str, Any]):
    """Busca la razón social en la web, guarda el flag de discrepancia y devuelve
    los hallazgos (`WebFindings`) o `None` si no aplica / degrada.

    Regla de oro: el correo SIEMPRE manda. La web solo (a) aporta contexto al
    resolver, (b) marca discrepancia para el dashboard y (c) alimenta la
    justificación.
    """
    settings = get_settings()
    if not (settings.web_lookup_enabled and settings.tavily_api_key):
        return None
    razon = fields.get("beneficiario_razon_social")
    if not razon:
        return None

    from .investigacion.comparador import compare_actividades
    from .investigacion.web_lookup import lookup_company

    findings = lookup_company(str(razon))
    if not findings.found:
        return None

    mismatch = compare_actividades(_correo_actividad(fields), findings)
    db.update_run(
        run_id,
        discrepancia_correo_web=mismatch.discrepancia,
        web_actividad_resumen=findings.resumen,
        web_fuentes_json=findings.fuentes,
    )
    if mismatch.discrepancia:
        logger.warning(
            "runner.discrepancia_correo_web",
            razon_social=razon,
            explicacion=mismatch.explicacion,
        )
    return findings


def _maybe_generar_justificacion(run_id: int, fields: dict[str, Any], findings) -> None:
    """Redacta la justificación (B30) si el correo no la trae. Degrada sin web."""
    if fields.get("justificacion_tecnica"):
        return  # respeta lo que ya venga del correo
    from .investigacion.justificacion import generar_justificacion

    try:
        texto = generar_justificacion(fields, findings)
    except Exception as e:  # noqa: BLE001
        logger.warning("runner.justificacion_failed", error=str(e))
        return
    if texto:
        fields["justificacion_tecnica"] = texto
        db.update_run(run_id, fields_json=fields)
        logger.info("runner.justificacion_generada", chars=len(texto))


def _correo_actividad(fields: dict[str, Any]) -> str:
    """Concatena la descripción de la actividad del correo (para comparar con la web)."""
    partes: list[str] = []
    for act in fields.get("actividades") or []:
        for key in ("actividad", "destino", "descripcion_rubro"):
            value = act.get(key)
            if value:
                partes.append(str(value))
    # Dedup preservando orden.
    return " · ".join(dict.fromkeys(partes))


def _render_outputs(
    fields: dict[str, Any], thread_id: str, contexto_web: str | None = None
) -> dict[str, Path]:
    """Consolida campos (defaults + códigos sec. 5 + cronograma) y renderiza Excel + PDF."""
    from .generacion.enricher import enrich_fields
    from .generacion.excel_writer import render_excel
    from .generacion.pdf_writer import render_pdf

    settings = get_settings()
    merged = enrich_fields(fields, contexto_web=contexto_web)

    out_dir = settings.output_dir / thread_id
    out_dir.mkdir(parents=True, exist_ok=True)
    excel_out = out_dir / "solicitud_credito.xlsx"
    render_excel(merged, excel_out)

    pdf_out: Path | None = None
    try:
        pdf_out = out_dir / "solicitud_credito.pdf"
        render_pdf(excel_out, pdf_out)
    except Exception as e:  # noqa: BLE001
        logger.warning("runner.pdf_failed", error=str(e))
        pdf_out = None

    return {"excel": excel_out, "pdf": pdf_out}


def _finish_and_tag(
    gmail: GmailClient, thread_id: str, run_id: int, status: str, mark_done: bool
) -> None:
    db.finish_run(run_id, status=status)
    if mark_done:
        try:
            done_id = gmail.get_or_create_label(get_settings().gmail_label_done)
            gmail.add_label_to_thread(thread_id, done_id)
            # No quitamos la etiqueta 'bot' para que el analista vea la huella.
        except Exception as e:  # noqa: BLE001
            logger.warning("runner.label_done_failed", error=str(e))


def list_pending_bot_threads(gmail: GmailClient | None = None) -> list[str]:
    """Hilos que tienen 'bot' pero aún no 'bot-procesado'."""
    settings = get_settings()
    gmail = gmail or GmailClient()
    gmail.authenticate(interactive=False)
    return gmail.list_threads_with_label(
        settings.gmail_label_trigger,
        exclude_label=settings.gmail_label_done,
    )
