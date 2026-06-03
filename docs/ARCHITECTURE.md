# Arquitectura

Documento vivo del diseño del sistema. Pareado con el diagrama `arquitectura_agropecuario.drawio` en la raíz.

---

## Visión general

El sistema es un **pipeline multi-agente trigger-based** que automatiza la formulación de proyectos de crédito agropecuario Finagro a partir de correos.

Estado: **producción interna**. Procesa hilos reales bajo supervisión humana (el analista decide qué hilo procesar aplicando la etiqueta `bot`).

---

## Componentes

### 1. Trigger — Gmail Label Watcher
- **Módulo**: `agropecuario/ingesta/gmail_client.py`
- **Comando**: `agropecuario watch-bot`
- Lista hilos con etiqueta `bot` que **no** tengan `bot-procesado`.
- Por cada hilo: hace `fetch_thread()` que devuelve mensajes ordenados cronológicamente.
- Al final aplica `bot-procesado` para evitar reproceso (idempotente por `(thread_id, last_message_id)`).

### 2. Aggregator — Consolidador de hilo
- **Módulo**: `agropecuario/ingesta/aggregator.py`
- Recibe un `EmailThread` (lista de `EmailMessage`).
- Concatena cuerpos en bloques `=== [Correo N/M] fecha — remitente ===` cronológicamente.
- Deduplica adjuntos por nombre — gana el más reciente (esto cubre el caso "correo de correcciones reemplaza al original").
- Devuelve un `EmailMessage` virtual + lista de `contributing_message_ids`.

### 3. Extractor — LLM
- **Módulo**: `agropecuario/ingesta/extractor.py`
- Llama al LLM (`OPENAI_MODEL`) con el cuerpo agregado + texto extraído de adjuntos.
- Parsers de adjuntos en `agropecuario/ingesta/parsers/`: PDF (pdfplumber + pypdf fallback), Excel (openpyxl/xlrd), Word (python-docx), imágenes (pytesseract OCR).
- Devuelve `ExtractedContent` con `thread_id`, `contributing_message_ids`, y el dict de campos.

### 4. Validator + GapManager
- **Módulos**: `agropecuario/validacion/{rule_engine,validator,gap_manager}.py`
- `RuleSet` se carga desde `config/rules.yaml` (campos requeridos + opcionales + reglas cruzadas).
- Cada campo se valida por tipo, regex, rango, valores permitidos.
- `GapManager.build_result()` calcula completitud (`requeridos`, `opcionales`) contra umbrales.
- Si no aprueba: `draft_reply_for_gaps()` redacta el correo de respuesta listando lo que falta.

### 5. Mapper + Generadores
- **Módulo `mapper.py`**: convierte `ExtractedContent` → diccionario plano de campos del template.
- **Módulo `enricher.py`**: cálculos derivados (sumas, cronograma, validaciones de consistencia).
- **`excel_writer.py`**: rellena `templates/credito_agro_template.xlsx` por mapeo `campo → celda` en `config/excel_cells.yaml`.
- **`pdf_writer.py`**: convierte el Excel a PDF con LibreOffice headless (`soffice --convert-to pdf`).

### 6. Storage
- **`storage/db.py`**: SQLite con 3 tablas:
  - `runs(id, thread_id, last_message_id, status, started_at, finished_at, error, fields_json, excel_path, pdf_path, drive_excel_url, drive_pdf_url, subject, sender, completitud_req, completitud_opt, aprobado, closed)`
  - `gaps(id, run_id, field_id, descripcion, tipo, sugerencia)`
  - `messages(id, run_id, message_id, received_at, sender, sender_name, subject, body_preview, attachments)`
- **Idempotencia**: clave compuesta `(thread_id, last_message_id)`. Reprocesar el mismo estado reusa el run; un correo nuevo crea uno nuevo.
- **`drive_client.py`**: sube Excel + PDF a `DRIVE_OUTPUT_FOLDER_ID`, devuelve URLs.

### 7. Dashboard — FastAPI
- **Módulo**: `agropecuario/ui/app.py`
- Routes:
  - `GET /` — métricas + últimos 10 runs.
  - `GET /threads?status=&in_progress=&closed=` — tabla filtrable.
  - `GET /threads/{id}` — detalle (timeline, brechas, campos, errores, descargas).
  - `POST /threads/{id}/reprocess` — fuerza re-fetch + reproceso.
  - `POST /threads/{id}/close` — cierra/reabre run.
  - `GET /threads/{id}/download/{kind}` — Excel/PDF locales.
  - `GET /api/metrics`, `GET /api/health` — APIs JSON.
- Templates Jinja2 + HTMX + Tailwind CDN. Sin build step.

---

## Diagrama de estados de un run

```
                    ┌──────────────────┐
                    │     pending      │  ← create_run
                    └────────┬─────────┘
                             │
                       extract(LLM)
                             │
                    ┌────────▼─────────┐
                    │    extracted     │
                    └────────┬─────────┘
                             │
                          validate
                             │
                  ┌──────────┴──────────┐
                  │                     │
                  ▼                     ▼
        ┌──────────────────┐  ┌──────────────────┐
        │   incomplete     │  │    approved      │
        │ (gaps > 0,       │  │ (completitud_req │
        │  completitud_req │  │   >= 0.85)       │
        │  < umbral)       │  └────────┬─────────┘
        └────────┬─────────┘           │
                 │                  generate
        send_reply_for_gaps            │
                 │              ┌──────▼──────┐
                 │              │  generated  │
                 │              └──────┬──────┘
                 │                     │
                 │              upload to Drive
                 │                     │
                 │              ┌──────▼──────┐
                 │              │  delivered  │
                 │              └─────────────┘
                 │
                 ▼
          (espera respuesta del cliente — nuevo correo creará nuevo run)


         Camino de error desde CUALQUIER punto:
                            │
                            ▼
                  ┌──────────────────┐
                  │      failed      │  (error registrado, visible en UI)
                  └──────────────────┘
```

---

## Contratos clave (Pydantic)

```python
class EmailMessage(BaseModel):
    message_id: str
    thread_id: str
    sender: str
    sender_name: str | None
    subject: str
    received_at: datetime
    body: str
    attachments: list[Attachment]

class EmailThread(BaseModel):
    thread_id: str
    messages: list[EmailMessage]
    triggered_at: datetime
    # propiedades: last_message_id, last_activity_at, subject, primary_sender

class ExtractedContent(BaseModel):
    thread_id: str
    contributing_message_ids: list[str]
    campos: dict[str, Any]
    confianza: dict[str, float]

class ValidationResult(BaseModel):
    campos: list[FieldValidation]
    gaps: list[Gap]
    completitud_requeridos: float
    completitud_opcionales: float
    aprobado: bool
    mensaje_resumen: str
```

---

## Decisiones de diseño

### Por qué label trigger en vez de polling INBOX
El analista mantiene el control. Procesar solo lo que él decide evita: (a) gastar tokens en spam o correos no-proyecto, (b) responder por error a hilos que el cliente aún no terminó de enviar, (c) errores caros en escala.

### Por qué agregar todo el hilo
Las solicitudes reales llegan en 3-10 correos: el inicial, correcciones, adjuntos extra, respuestas a preguntas. Procesar solo el último mensaje rompe; procesar cada uno por separado duplica trabajo. Agregación cronológica + dedup de adjuntos por nombre = el LLM ve la versión consolidada con correcciones aplicadas.

### Por qué SQLite (no Postgres)
- Single-node, single-tenant interno.
- Idempotencia por clave compuesta — SQLite es perfectamente capaz.
- Migración a Postgres cuando llegue multi-tenancy o RPS sostenido > 1.

### Por qué LibreOffice para PDF
- WeasyPrint requiere construir HTML del template, que tiene 200+ celdas con fórmulas.
- LibreOffice convierte el Excel directamente respetando estilos y fórmulas calculadas.
- Trade-off: latencia ~3-5s por PDF; aceptable para volumen actual.

### Por qué FastAPI + Jinja + HTMX
- No queremos un SPA. La UI es CRUD + visualización.
- Server-side rendering = un solo deploy, sin pipeline JS.
- HTMX cubre las pocas interacciones dinámicas (filtros, reprocesar).
- Tailwind CDN es OK para uso interno; reemplazar antes de exponer públicamente.

---

## No implementado todavía

Ver el roadmap en el README. Específicamente las tareas `#14`, `#15`, `#16` que cierran el ciclo end-to-end con LLM real.
