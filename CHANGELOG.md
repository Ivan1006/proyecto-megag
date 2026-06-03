# Changelog

Todo cambio notable en este proyecto se documenta aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y este proyecto adhiere a [Semantic Versioning](https://semver.org/lang/es/).

---

## [Unreleased]

### Pendiente
- `#14` Módulo `catalogo/` + sub-agente `code_resolver`.
- `#15` Reescribir `mapper.py` con prompt Finagro completo.
- `#16` Enricher con cálculos (`=SUM`, cronograma).

---

## [0.2.0] — 2026-06-02

### Added
- **Trigger por etiqueta Gmail (`bot` / `bot-procesado`)**. El analista decide qué hilo procesar.
- **Aggregator de hilos**: consolida correos múltiples cronológicamente con `=== [Correo N/M] ===`, deduplica adjuntos por nombre (gana el más reciente).
- **Persistencia SQLite** (`storage/db.py`): tablas `runs`, `gaps`, `messages` con idempotencia por `(thread_id, last_message_id)`.
- **CLI**: `process-thread`, `watch-bot`, `ui`, `db-init`, `seed-demo`.
- **Dashboard FastAPI + HTMX + Tailwind**:
  - `/` con KPIs clicables (Generados / Pendientes / Incompletos / Fallidos).
  - `/threads` con filtros por estado, avance, cerrados; badges activos removibles; preview del error en runs `failed`.
  - `/threads/{id}` con banner prominente de error, timeline cronológico, brechas, campos, descargas.
  - Acciones POST: reprocesar, cerrar/reabrir.
  - APIs JSON: `/api/metrics`, `/api/health`.
- Modelo `EmailThread` y campos `thread_id` + `contributing_message_ids` en `ExtractedContent`.

### Changed
- `gmail_client.py`: nuevos helpers `get_or_create_label`, `list_threads_with_label`, `fetch_thread` (ordenado), `add_label_to_thread`, `remove_label_from_thread`, `send_reply` (MIME + threadId).

---

## [0.1.0] — 2026-04-20

### Added
- Esqueleto del proyecto.
- Orquestador LangGraph con 3 agentes (ingesta, validación, generación).
- Parsers de adjuntos: PDF, Excel, Word, imágenes (OCR).
- Motor de reglas configurable (`rules.yaml`).
- Generación de entregables Excel (template fill) + PDF (LibreOffice headless).
- Subida a Google Drive.
