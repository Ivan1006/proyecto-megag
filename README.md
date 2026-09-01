# Proyecto MegaG — Agente Agropecuario

Sistema multi-agente que automatiza el flujo de **formulación de proyectos de crédito agropecuario Finagro / Bancolombia** a partir de correos de Gmail.

El analista solo aplica la etiqueta `bot` a un hilo de correo. El sistema:

1. Lee todo el hilo (correo inicial + correcciones + adjuntos).
2. Lo agrega cronológicamente y consolida adjuntos.
3. Extrae los campos del formulario con LLM.
4. Valida contra reglas de negocio (`config/rules.yaml`).
5. Si faltan datos → redacta y responde al remitente pidiendo lo que falta.
6. Si está completo → genera el Excel + PDF del proyecto en `data/output/<thread_id>/`.
7. Etiqueta el hilo como `bot-procesado` para evitar reproceso.

Toda la trazabilidad queda persistida en SQLite y visible en un **dashboard web**.

---

## Capacidades actuales

### Ingesta inteligente de hilos
- Trigger por etiqueta (`bot`) — el analista mantiene el control.
- Agregación cronológica: cuando una solicitud llega repartida en 3 / 5 / 10 correos (info inicial + correcciones + adjuntos extra), el sistema los une como bloques `=== [Correo N/M] fecha — remitente ===` para que el LLM vea la versión "final corregida".
- Deduplicación de adjuntos por nombre — gana el más reciente.

### Extracción y validación
- Extracción LLM hacia `ExtractedContent` con `thread_id` y `contributing_message_ids`.
- Motor de reglas configurable (`config/rules.yaml`): tipo, regex, rango, valores permitidos.
- Detección de brechas tipadas (`faltante`, `fuera_de_rango`, `formato_invalido`, `inconsistencia`).
- Redacción automática de correo solicitando información faltante.

### Persistencia y trazabilidad
- SQLite con 3 tablas: `runs`, `gaps`, `messages`.
- Idempotencia por `(thread_id, last_message_id)`: reprocesar el mismo estado del hilo reusa el run; un correo nuevo crea uno nuevo.

### Dashboard web (FastAPI + Jinja + HTMX + Tailwind)
- **`/`** — KPIs clicables (Generados, Pendientes, Incompletos, Fallidos) y últimos runs.
- **`/threads`** — Tabla filtrable por estado / avance / cerrados; los runs `failed` muestran preview + tooltip del error.
- **`/threads/{id}`** — Detalle con banner de error prominente cuando falla, timeline cronológico de mensajes con adjuntos, brechas detectadas, campos extraídos, y descargas del Excel y el PDF.
- Acciones: reprocesar hilo, cerrar/reabrir run, descargar entregables.

### Generación de entregables
- Excel: rellenado del template oficial por mapeo `campo → celda` (`config/excel_cells.yaml`).
- PDF: conversión vía LibreOffice headless.
- Los entregables quedan en `data/output/<thread_id>/`. **No se suben a ningún
  lado**: Google Drive se descartó y la entrega definitiva (correo o una ruta de
  NAS) está sin definir.

---

## Arquitectura

```
┌────────────┐   etiqueta "bot"    ┌───────────────┐
│   Gmail    │ ─────────────────▶ │  Watcher /    │
│  (analista)│                     │  CLI runner   │
└────────────┘                     └───────┬───────┘
                                           │
                                           ▼
                          ┌─────────────────────────────┐
                          │   Aggregator (hilo entero)  │
                          └──────────────┬──────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │  Extractor LLM (OpenAI)     │
                          └──────────────┬──────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │  Validator + GapManager     │
                          └──────┬──────────────────┬───┘
                  brechas?       │                  │   ok
                                 ▼                  ▼
                 ┌──────────────────────┐  ┌─────────────────────┐
                 │ Reply al remitente   │  │ Mapper → Excel/PDF  │
                 │ pidiendo info        │  │ → data/output/      │
                 └──────────────────────┘  └─────────────────────┘
                                 │                  │
                                 └────────┬─────────┘
                                          ▼
                          ┌─────────────────────────────┐
                          │  SQLite + Dashboard FastAPI │
                          └─────────────────────────────┘
```

Diagrama completo en `arquitectura_agropecuario.drawio`.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Lenguaje | Python 3.11+ |
| Orquestación | LangGraph + LangChain |
| LLM | OpenAI (GPT-4o / GPT-4o-mini) |
| Email | Gmail API |
| Datos | Pydantic v2, SQLite |
| Generación | openpyxl (Excel), LibreOffice (PDF), Jinja2 |
| Web UI | FastAPI + Jinja2 + HTMX + Tailwind CDN |
| CLI | Typer + Rich |

---

## Instalación

### Requisitos
- Python ≥ 3.11
- LibreOffice (para conversión PDF) — `sudo pacman -S libreoffice-still` / `apt install libreoffice`
- Credenciales OAuth de Google Cloud Console con scope `gmail.modify`

### Setup

```bash
git clone https://github.com/Ivan1006/proyecto-megag.git
cd proyecto-megag

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

cp .env.example .env
# Editar .env con tus credenciales (OPENAI_API_KEY, etc.)

# Colocar credenciales Google
mkdir -p secrets
# Descargar client_secret.json desde Google Cloud Console → secrets/

# Inicializar BD
agropecuario db-init
```

---

## Uso

### CLI

```bash
# Autenticar Gmail (primera vez — abre navegador)
agropecuario auth

# Procesar un hilo específico
agropecuario process-thread <thread_id>

# Modo watch: escanea cada N segundos los hilos con etiqueta "bot"
agropecuario watch-bot

# Lanzar dashboard web
agropecuario ui
#   → http://127.0.0.1:8000

# Sembrar datos demo (5 runs de muestra)
agropecuario seed-demo
```

### Flujo del analista

1. Recibe un correo de cliente con solicitud de crédito.
2. Aplica la etiqueta `bot` en Gmail.
3. El sistema procesa el hilo automáticamente.
4. Si faltan datos, el cliente recibe respuesta pidiendo lo que falta.
5. Cuando el cliente responde, el analista vuelve a aplicar `bot` (o el watcher detecta el cambio).
6. Cuando el proyecto está completo, recibe el Excel + PDF generados.
7. Toda la trazabilidad queda en el dashboard.

---

## Estructura

```
proyecto-megag/
├── src/agropecuario/
│   ├── agents/          # Nodos LangGraph (ingesta, validacion, generacion)
│   ├── ingesta/         # Gmail client, aggregator, parsers (PDF/Excel/Word/imágenes)
│   ├── validacion/      # Rule engine, validator, gap manager
│   ├── generacion/      # Mapper, enricher, Excel/PDF writers
│   ├── storage/         # SQLite (db.py), seed de demo, almacén temporal
│   ├── ui/              # FastAPI dashboard + templates
│   ├── orchestrator.py  # Grafo LangGraph
│   ├── runner.py        # Orquestador por hilo (label trigger)
│   ├── models.py        # Contratos Pydantic (EmailMessage, EmailThread, etc.)
│   ├── settings.py      # Configuración por env vars
│   └── cli.py           # Entrypoint Typer
├── config/
│   ├── rules.yaml             # Reglas de validación
│   ├── excel_cells.yaml       # Mapeo campo → celda Excel
│   ├── defaults.yaml          # Valores hardcoded
│   ├── template.yaml          # Template del proyecto
│   └── catalogo_destinos.xlsx # Catálogo Finagro
├── templates/
│   ├── credito_agro_template.xlsx
│   ├── proyecto.html.j2
│   └── proyecto.css
├── tests/
├── docs/
│   ├── ARCHITECTURE.md
│   └── BRANCHING.md
├── .github/
│   ├── workflows/ci.yml
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── pyproject.toml
├── CONTRIBUTING.md
└── README.md
```

---

## Configuración

Todas las variables vía `.env`. Ver `.env.example` para la lista completa.

Variables clave:

| Variable | Descripción |
|----------|-------------|
| `OPENAI_API_KEY` | API key de OpenAI |
| `OPENAI_MODEL` | Modelo principal (default `gpt-4o`) |
| `GOOGLE_CLIENT_SECRETS` | Ruta al `client_secret.json` |
| `GMAIL_LABEL_TRIGGER` | Etiqueta que dispara el bot (default `bot`) |
| `GMAIL_LABEL_DONE` | Etiqueta para marcar procesados (default `bot-procesado`) |
| `DB_PATH` | Ruta a la SQLite local |
| `RULES_PATH` | Ruta a `rules.yaml` |
| `UI_HOST` / `UI_PORT` | Bind del dashboard (default `127.0.0.1:8000`) |

---

## Tests

```bash
pytest                       # Toda la suite
pytest tests/test_rules.py   # Un módulo
ruff check src/              # Lint
mypy src/                    # Tipos
```

---

## Roadmap

- [ ] **#14** Módulo `catalogo/` + sub-agente `code_resolver` (resolución LLM de actividades sobre el Anexo de 1129 filas).
- [ ] **#15** Reescribir `mapper.py` para cubrir todos los campos del formulario Finagro.
- [ ] **#16** Enricher con cálculos del formulario (validación `=SUM`, cronograma).
- [ ] Reemplazar Tailwind CDN por build local.
- [ ] Métricas + alertas (Prometheus / Grafana).
- [ ] CI con cobertura mínima.

---

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md) y [docs/BRANCHING.md](docs/BRANCHING.md).

---

## Licencia

Proyecto privado. Todos los derechos reservados.
