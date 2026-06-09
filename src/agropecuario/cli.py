"""CLI del agente — entrada para auth, corridas puntuales y modo watch."""

from __future__ import annotations

import json
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .ingesta.gmail_client import GmailClient
from .logging_conf import configure_logging, get_logger
from .settings import get_settings

app = typer.Typer(add_completion=False, help="Agente Generador de Proyectos Agropecuarios")
console = Console()
logger = get_logger(__name__)


@app.callback()
def _bootstrap() -> None:
    configure_logging()
    get_settings().ensure_dirs()


@app.command()
def auth() -> None:
    """Lanza el flujo OAuth de Google (primera vez)."""
    gmail = GmailClient()
    gmail.authenticate(interactive=True)
    console.print("[green]Autenticación completa.[/green]")


@app.command()
def run(message_id: str = typer.Option(..., "--message-id", "-m"),
        no_drive: bool = typer.Option(False, help="No subir a Drive")) -> None:
    """Procesa un correo específico por ID (grafo LangGraph end-to-end Finagro)."""
    from .orchestrator import run_for_message
    result = run_for_message(message_id, enable_drive=not no_drive)
    console.print(f"[bold]Estado final:[/bold] {result.get('status')}")
    outputs = result.get("outputs")
    if outputs:
        console.print(f"PDF:   {outputs.pdf_path}")
        console.print(f"Excel: {outputs.excel_path}")


@app.command()
def watch(interval: int = typer.Option(60, help="Segundos entre polls")) -> None:
    """Modo continuo: consulta Gmail periódicamente."""
    from .orchestrator import run_for_message
    gmail = GmailClient()
    gmail.authenticate(interactive=False)
    seen: set[str] = set()
    while True:
        ids = gmail.list_messages()
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            try:
                run_for_message(mid)
            except Exception as e:  # noqa: BLE001
                logger.error("watch.run_failed", message_id=mid, error=str(e))
        time.sleep(interval)


@app.command()
def list_messages(limit: int = 10) -> None:
    """Lista los correos que matchean el filtro configurado."""
    gmail = GmailClient()
    gmail.authenticate(interactive=False)
    ids = gmail.list_messages(max_results=limit)
    table = Table(title="Correos pendientes")
    table.add_column("#")
    table.add_column("Message ID")
    for i, mid in enumerate(ids, start=1):
        table.add_row(str(i), mid)
    console.print(table)


@app.command("extract-local")
def extract_local(
    files: list[Path] = typer.Option(
        None, "--file", "-f", help="Ruta a un adjunto local (repetible)"
    ),
    body: str = typer.Option("", "--body", "-b", help="Texto del cuerpo del correo simulado"),
    body_file: Path = typer.Option(
        None, "--body-file", help="Leer el cuerpo desde un archivo de texto"
    ),
    no_llm: bool = typer.Option(False, "--no-llm", help="Solo parsear, sin llamar a OpenAI"),
    max_chars: int = typer.Option(3000, help="Caracteres máximos a mostrar del texto combinado"),
) -> None:
    """Prueba la ingesta sobre archivos locales (sin OAuth).

    Útil para validar parsers + mapper antes de configurar Gmail.
    """
    from .ingesta.extractor import extract
    from .models import Attachment, EmailMessage

    if body_file:
        body = body_file.read_text(encoding="utf-8")

    attachments: list[Attachment] = []
    for f in files or []:
        if not f.exists():
            console.print(f"[red]No existe:[/red] {f}")
            raise typer.Exit(code=1)
        mime, _ = mimetypes.guess_type(str(f))
        attachments.append(
            Attachment(
                filename=f.name,
                mime_type=mime or "application/octet-stream",
                size_bytes=f.stat().st_size,
                local_path=f,
            )
        )

    email = EmailMessage(
        message_id="LOCAL-TEST",
        thread_id="LOCAL-TEST",
        sender="test@local.dev",
        sender_name="Prueba local",
        subject="Prueba local de ingesta",
        received_at=datetime.now(timezone.utc),
        body_plain=body,
        attachments=attachments,
    )

    console.rule("[bold]1. Parseo de adjuntos")
    extracted = extract(email)
    for att in extracted.email.attachments:
        size = len(att.extracted_text or "")
        console.print(f"  • {att.filename} ({att.mime_type}) → {size} chars")

    console.rule("[bold]2. Texto combinado")
    text = extracted.combined_text
    console.print(text[:max_chars])
    if len(text) > max_chars:
        console.print(f"\n[dim]... ({len(text)} chars en total)[/dim]")

    if no_llm:
        console.rule("[yellow]Mapper LLM omitido (--no-llm)")
        return

    console.rule("[bold]3. Mapeo LLM → campos")
    from .generacion.mapper import map_content_to_fields
    from .validacion.rule_engine import load_rules

    settings = get_settings()
    if not settings.openai_api_key:
        console.print("[red]Falta OPENAI_API_KEY en .env. Usa --no-llm para saltar este paso.[/red]")
        raise typer.Exit(code=1)

    rules = load_rules(settings.rules_path)
    fields = map_content_to_fields(text, rules)
    console.print(json.dumps(fields, indent=2, ensure_ascii=False))

    console.rule("[bold]4. Validación contra reglas")
    from .validacion.gap_manager import build_result
    from .validacion.validator import validate_fields

    validations = validate_fields(fields, rules)
    result = build_result(validations, rules)
    console.print(
        f"Aprobado: [{'green' if result.aprobado else 'red'}]{result.aprobado}[/]  "
        f"Requeridos: {result.completitud_requeridos:.0%}  "
        f"Opcionales: {result.completitud_opcionales:.0%}"
    )
    if result.gaps:
        console.print("\n[bold]Brechas detectadas:[/bold]")
        for g in result.gaps:
            console.print(f"  • {g.field_id} [{g.tipo}] — {g.descripcion}")


@app.command("fill-template")
def fill_template(
    data: Path = typer.Option(..., "--data", "-d", help="JSON con los campos del formulario"),
    output_dir: Path = typer.Option(
        Path("./data/output"), "--out", "-o", help="Carpeta de salida"
    ),
    no_pdf: bool = typer.Option(False, "--no-pdf", help="No generar PDF (solo Excel)"),
) -> None:
    """Rellena el formulario Bancolombia/Finagro con datos JSON y genera Excel + PDF.

    Sirve para verificar el flujo de generación sin pasar por Gmail/LLM.
    """
    import yaml as _yaml

    from .generacion.excel_writer import render_excel
    from .generacion.pdf_writer import render_pdf

    payload = json.loads(data.read_text(encoding="utf-8"))

    defaults_path = Path("./config/defaults.yaml")
    if defaults_path.exists():
        defaults = _yaml.safe_load(defaults_path.read_text(encoding="utf-8")) or {}
        # los datos del payload tienen prioridad sobre los defaults
        merged = {**defaults, **payload}
    else:
        merged = payload

    output_dir.mkdir(parents=True, exist_ok=True)
    excel_out = output_dir / f"{data.stem}.xlsx"
    render_excel(merged, excel_out)
    console.print(f"[green]Excel generado:[/green] {excel_out}")

    if not no_pdf:
        pdf_out = output_dir / f"{data.stem}.pdf"
        render_pdf(excel_out, pdf_out)
        console.print(f"[green]PDF generado:[/green] {pdf_out}")


@app.command("extract-gmail")
def extract_gmail(
    message_id: str = typer.Option(
        None, "--message-id", "-m",
        help="ID del mensaje Gmail. Si se omite, usa el primero del filtro.",
    ),
    no_llm: bool = typer.Option(False, "--no-llm", help="Solo parsear, sin OpenAI"),
    max_chars: int = typer.Option(3000, help="Caracteres a mostrar del texto combinado"),
) -> None:
    """Agente 1 sobre Gmail real: descarga un correo y muestra los campos extraídos.

    No pasa por validación ni generación — es solo la etapa de ingesta.
    """
    from .ingesta.extractor import extract

    gmail = GmailClient()
    gmail.authenticate(interactive=False)

    if not message_id:
        ids = gmail.list_messages(max_results=1)
        if not ids:
            console.print("[yellow]No se encontraron correos con el filtro configurado.[/yellow]")
            raise typer.Exit(code=1)
        message_id = ids[0]
        console.print(f"[dim]Usando primer correo: {message_id}[/dim]")

    console.rule(f"[bold]1. Descarga del correo {message_id}")
    email = gmail.fetch_message(message_id)
    console.print(f"De: {email.sender_name or ''} <{email.sender}>")
    console.print(f"Asunto: {email.subject}")
    console.print(f"Recibido: {email.received_at}")
    console.print(f"Adjuntos: {len(email.attachments)}")

    console.rule("[bold]2. Parseo de adjuntos")
    extracted = extract(email)
    for att in extracted.email.attachments:
        size = len(att.extracted_text or "")
        console.print(f"  • {att.filename} ({att.mime_type}) → {size} chars, "
                      f"guardado en {att.local_path}")

    console.rule("[bold]3. Texto combinado")
    text = extracted.combined_text
    console.print(text[:max_chars])
    if len(text) > max_chars:
        console.print(f"\n[dim]... ({len(text)} chars en total)[/dim]")

    if no_llm:
        console.rule("[yellow]Mapper LLM omitido (--no-llm)")
        return

    console.rule("[bold]4. Mapeo LLM → campos")
    from .generacion.mapper import map_content_to_fields
    from .validacion.rule_engine import load_rules

    settings = get_settings()
    if not settings.openai_api_key:
        console.print("[red]Falta OPENAI_API_KEY en .env. Usa --no-llm para saltar.[/red]")
        raise typer.Exit(code=1)

    rules = load_rules(settings.rules_path)
    fields = map_content_to_fields(text, rules)
    console.print(json.dumps(fields, indent=2, ensure_ascii=False))


@app.command("process-thread")
def process_thread_cmd(
    thread_id: str = typer.Option(..., "--thread-id", "-t", help="ID del hilo Gmail"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Solo extraer + persistir"),
    no_render: bool = typer.Option(False, "--no-render", help="No generar Excel/PDF"),
    no_label: bool = typer.Option(False, "--no-label", help="No marcar bot-procesado"),
) -> None:
    """Procesa un hilo completo (todos sus correos) y deja registro en SQLite."""
    from .runner import process_thread

    run_id = process_thread(
        thread_id,
        use_llm=not no_llm,
        render=not no_render,
        mark_done=not no_label,
    )
    console.print(f"[green]Run #{run_id} creado para el hilo[/green] {thread_id}")


@app.command("watch-bot")
def watch_bot(
    interval: int = typer.Option(60, help="Segundos entre polls"),
    once: bool = typer.Option(False, "--once", help="Recorrer una sola vez y salir"),
    no_llm: bool = typer.Option(False, "--no-llm"),
    no_render: bool = typer.Option(False, "--no-render"),
) -> None:
    """Polling de Gmail buscando hilos con la etiqueta 'bot' y procesándolos.

    Sólo procesa hilos que NO tengan ya la etiqueta 'bot-procesado'.
    """
    from .runner import list_pending_bot_threads, process_thread

    settings = get_settings()
    console.print(
        f"[bold]Etiqueta trigger:[/bold] '{settings.gmail_label_trigger}'  "
        f"[bold]marcador done:[/bold] '{settings.gmail_label_done}'"
    )

    gmail = GmailClient()
    gmail.authenticate(interactive=False)

    while True:
        threads = list_pending_bot_threads(gmail)
        if threads:
            console.print(f"[cyan]{len(threads)} hilo(s) pendiente(s)[/cyan]")
            for tid in threads:
                try:
                    run_id = process_thread(
                        tid,
                        gmail=gmail,
                        use_llm=not no_llm,
                        render=not no_render,
                    )
                    console.print(f"  ✓ hilo {tid} → run #{run_id}")
                except Exception as e:  # noqa: BLE001
                    console.print(f"  [red]✗ hilo {tid} falló:[/red] {e}")
        elif not once:
            console.print(f"[dim]Sin pendientes. Esperando {interval}s...[/dim]")

        if once:
            return
        time.sleep(interval)


@app.command("ui")
def ui_cmd(
    host: str = typer.Option(None, help="Host (default: settings.ui_host)"),
    port: int = typer.Option(None, help="Puerto (default: settings.ui_port)"),
    reload: bool = typer.Option(False, "--reload", help="Recarga en cambios (dev)"),
) -> None:
    """Lanza el dashboard web de trazabilidad."""
    import uvicorn

    from .storage.db import init_db

    settings = get_settings()
    init_db()
    h = host or settings.ui_host
    p = port or settings.ui_port
    console.print(f"[bold green]Dashboard:[/bold green] http://{h}:{p}")
    uvicorn.run(
        "agropecuario.ui.app:app",
        host=h,
        port=p,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@app.command("db-init")
def db_init() -> None:
    """Crea las tablas SQLite (idempotente)."""
    from .storage.db import init_db

    init_db()
    console.print("[green]DB lista.[/green]")


@app.command("seed-demo")
def seed_demo() -> None:
    """Inserta runs de prueba para ver la UI sin necesitar Gmail."""
    from .storage import seed

    seed.run()
    console.print("[green]Datos demo cargados.[/green]")


if __name__ == "__main__":
    app()
