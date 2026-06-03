"""Dashboard FastAPI: trazabilidad del agente.

Páginas (HTML, server-side rendering con Jinja2 + HTMX para interactividad):

    GET  /                          → Dashboard con KPIs.
    GET  /threads                   → Lista paginable de runs.
    GET  /threads/{run_id}          → Detalle del run (timeline + gaps + outputs).
    POST /threads/{run_id}/reprocess   → Re-ejecuta el procesamiento del hilo.
    POST /threads/{run_id}/close       → Marca el run como cerrado.
    GET  /threads/{run_id}/download/{kind}  → Descarga el Excel o el PDF.
    GET  /api/metrics               → KPIs en JSON (para gráficas).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..logging_conf import configure_logging, get_logger
from ..settings import get_settings
from ..storage import db

configure_logging()
logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Agropecuario Agent — Trazabilidad")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# --- filtros Jinja útiles ---------------------------------------------------

def _humanize_ms(ms: int | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms} ms"
    s = ms / 1000
    if s < 60:
        return f"{s:.1f} s"
    return f"{s / 60:.1f} min"


def _short_id(value: str | None, n: int = 12) -> str:
    if not value:
        return "—"
    return value if len(value) <= n else value[:n] + "…"


def _parse_json(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:  # noqa: BLE001
        return None


def _status_color(status: str) -> str:
    return {
        "pending":     "bg-slate-200 text-slate-700",
        "extracted":   "bg-sky-100 text-sky-800",
        "incomplete":  "bg-amber-100 text-amber-800",
        "approved":    "bg-emerald-100 text-emerald-800",
        "generated":   "bg-emerald-200 text-emerald-900",
        "delivered":   "bg-emerald-300 text-emerald-900",
        "failed":      "bg-rose-200 text-rose-900",
    }.get(status, "bg-slate-100 text-slate-700")


templates.env.filters["humanize_ms"] = _humanize_ms
templates.env.filters["short_id"] = _short_id
templates.env.filters["from_json"] = _parse_json
templates.env.filters["status_color"] = _status_color


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    metrics = db.dashboard_metrics()
    recent = db.list_runs(limit=10)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"metrics": metrics, "recent": recent, "active": "dashboard"},
    )


@app.get("/threads", response_class=HTMLResponse)
def threads_list(
    request: Request,
    status: str | None = None,
    closed: int | None = None,
    in_progress: int | None = None,
    limit: int = 100,
):
    in_prog_bool = bool(in_progress) if in_progress is not None else None
    runs = db.list_runs(
        limit=limit, status=status, closed=closed, in_progress=in_prog_bool
    )
    return templates.TemplateResponse(
        request,
        "threads.html",
        {
            "runs": runs,
            "filter_status": status or "",
            "filter_closed": closed,
            "filter_in_progress": in_progress,
            "active": "threads",
        },
    )


@app.get("/threads/{run_id}", response_class=HTMLResponse)
def thread_detail(request: Request, run_id: int):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run no encontrado")
    return templates.TemplateResponse(
        request,
        "thread_detail.html",
        {"run": run, "active": "threads"},
    )


# ---------------------------------------------------------------------------
# Acciones (POST)
# ---------------------------------------------------------------------------

@app.post("/threads/{run_id}/reprocess")
def reprocess(run_id: int):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run no encontrado")
    thread_id = run["thread_id"]
    try:
        from ..runner import process_thread

        new_run_id = process_thread(thread_id)
        return RedirectResponse(url=f"/threads/{new_run_id}", status_code=303)
    except Exception as e:  # noqa: BLE001
        logger.error("ui.reprocess_failed", run_id=run_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Reproceso falló: {e}") from e


@app.post("/threads/{run_id}/close")
def close_thread(run_id: int):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run no encontrado")
    db.mark_closed(run_id, closed=not run.get("closed"))
    return RedirectResponse(url=f"/threads/{run_id}", status_code=303)


@app.get("/threads/{run_id}/download/{kind}")
def download(run_id: int, kind: str):
    if kind not in {"excel", "pdf"}:
        raise HTTPException(status_code=400, detail="kind debe ser excel o pdf")
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run no encontrado")
    path = run.get(f"{kind}_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail=f"No hay {kind} para este run")
    media = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if kind == "excel"
        else "application/pdf"
    )
    return FileResponse(path, media_type=media, filename=Path(path).name)


# ---------------------------------------------------------------------------
# API JSON
# ---------------------------------------------------------------------------

@app.get("/api/metrics")
def api_metrics():
    return JSONResponse(db.dashboard_metrics())


@app.get("/api/health")
def health():
    settings = get_settings()
    return {"ok": True, "env": settings.app_env}
