# CLAUDE.md — proyecto MegaG

Agente multi-etapa que convierte hilos de Gmail en la **Solicitud de Crédito
Agropecuario Finagro / Bancolombia** rellenada (Excel + PDF) y la deja en Drive.

---

## Documentación de referencia

Toda la documentación de fondo vive en mi vault de Obsidian. **No la importes**
en este archivo (no uses `@`); léela bajo demanda solo cuando la necesites para
una tarea concreta.

Ruta del vault: `/home/ivan1006/Documents/proyecto-megag/`

| Nota | Para qué |
|---|---|
| `MOC - MegaG.md` | Índice del proyecto. Empieza aquí. |
| `Arquitectura.md` | Flujo de los 3 agentes LangGraph (diagrama mermaid), responsabilidades, adjuntos esperados. |
| `Estructura del repo.md` | Árbol de carpetas y rol de cada módulo. |
| `Estado del proyecto.md` | Sub-fases completadas / en curso. |
| `Decisiones tecnicas.md` | Stack y justificación de las decisiones de diseño. |
| `Tareas pendientes.md` | Detalle técnico de `code_resolver`, `mapper`, `enricher`. |
| `Diario de sesiones.md` | Registro cronológico de sesiones; léelo al iniciar. |

---
## Rutina de inicio de sesión

Al empezar a trabajar, lee `Estado del proyecto.md` y la última entrada de
`Diario de sesiones.md` en el vault para retomar el contexto antes de actuar.

## Rutina de cierre de sesión

Antes de terminar, actualiza en el vault:
- `Estado del proyecto.md` — qué quedó hecho y qué cambió.
- `Tareas pendientes.md` — ajusta el estado de cada tarea.
- `Diario de sesiones.md` — agrega una entrada con fecha: qué se hizo, qué se
  intentó, qué quedó a medias y el próximo paso concreto.


## Stack (resumen)

Python 3.11+ · LangGraph + LangChain · OpenAI (GPT-4o / 4o-mini) ·
Gmail + Drive API · Pydantic v2 · openpyxl · LibreOffice headless ·
SQLite · FastAPI + Jinja + HTMX · Typer · structlog.

---

## Comandos

```bash
# Entorno
source .venv/bin/activate
pip install -e ".[dev]"

# OAuth Google (primera vez)
agropecuario auth

# Smoke test sin Gmail ni LLM
agropecuario fill-template --data data/samples/credito_demo.json

# Gmail
agropecuario list-messages --limit 5
agropecuario extract-gmail [-m <message_id>] [--no-llm]
agropecuario extract-local --file <path>

# Flujo por hilo (label trigger)
agropecuario process-thread <thread_id>
agropecuario watch-bot                  # polling de la etiqueta `bot`
agropecuario run -m <message_id>        # end-to-end (legacy, pendiente cablear Finagro)

# Dashboard + BD
agropecuario db-init
agropecuario seed-demo
agropecuario ui                         # http://127.0.0.1:8000

# Tests / lint
pytest -v
ruff check src/ tests/
mypy src/agropecuario
```

---

## Convenciones

- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:` …).
- **Ramas**: `feature/<n>-<slug>` desde `develop`; `hotfix/<n>-<slug>` desde
  `main`. PR a `develop`. Detalle en `CONTRIBUTING.md` y `docs/BRANCHING.md`.
- **Configuración**: cualquier campo / regla / mapeo nuevo va en `config/*.yaml`,
  no en Python.
- **Modelos**: Pydantic v2 en todo modelo nuevo.
- **Tests**: cada feature trae test; cada bug fix incluye test que reproduce
  el bug antes del arreglo.
- **Formato**: `ruff format`; lint con `ruff check`; tipos con `mypy`.

---

## Guardarraíles

### Secretos — nunca commitear
- `.env`, `secrets/client_secret.json`, `secrets/token.json` están en
  `.gitignore`. No los muevas fuera de ese path ni los inlinees en código.
- Si por error subes una credencial: rotarla y limpiar historial con
  `git filter-repo` (no `filter-branch`).
- Datos sintéticos para tests van en `data/samples/`; nunca usar datos reales
  de clientes en tests.

### Código legacy — no tocar
Estos archivos son del enfoque anterior (WeasyPrint / template HTML) y **no
forman parte del flujo Finagro**. No los modifiques ni los uses como referencia
para código nuevo:

- `config/template.yaml`
- `templates/proyecto.html.j2`
- `templates/proyecto.css`
- `src/agropecuario/generacion/template_engine.py`

**Aclaración sobre Jinja**: los ÚNICOS archivos Jinja legacy son
`templates/proyecto.html.j2` y `templates/proyecto.css` (de la generación de
PDF anterior con WeasyPrint). Las plantillas Jinja del **dashboard**
(FastAPI + HTMX, comando `agropecuario ui`, en
`src/agropecuario/ui/templates/`) son ACTIVAS y editables — no confundirlas
con las legacy.

Si tropiezas con los archivos legacy durante una tarea, **avísame antes** de
borrarlos o refactorizarlos — pueden seguir referenciados desde algún test
viejo.

### Formulario oficial — preservar fidelidad
- `templates/credito_agro_template.xlsx` se rellena celda a celda; **nunca**
  regenerar el Excel desde cero.
- Las fórmulas `=SUM(...)` del template se respetan; el `enricher` valida
  contra ellas, no las reemplaza.
- Sección 10 (firma del funcionario verificador) **se deja en blanco**
  intencionalmente.
- **Verificación obligatoria**: tras editar `excel_writer.py` o `enricher.py`,
  ejecutar `agropecuario fill-template --data data/samples/credito_demo.json`
  y confirmar que el Excel y el PDF salen idénticos al template ANTES de dar
  la tarea por terminada.

---

## Foco actual

Cerrar **Sub-fase 1.B** (end-to-end correo → Finagro con LLM real) en orden:

1. Módulo `catalogo/` + sub-agente `code_resolver` (tabla actividades sec. 5).
2. Reescribir `src/agropecuario/generacion/mapper.py` con prompt para campos
   Finagro (`beneficiario_*`, `predio_*`, `tenencia`, `garantia_fag`, …).
3. Actualizar `src/agropecuario/generacion/enricher.py` con cálculos del
   formulario y cablear `src/agropecuario/agents/generacion.py` al grafo
   LangGraph.

Detalle técnico de cada una en `Tareas pendientes.md` del vault.

---

## Cómo anotar en Obsidian

Cuando documente decisiones, avances, ideas o aprendizajes:

- Crear **una nota por tema** en `/home/ivan1006/Documents/proyecto-megag/`,
  con nombre descriptivo (`<Tema>.md`).
- Frontmatter YAML mínimo:
  ```yaml
  ---
  tags: [proyecto-megag, <tema>]
  fecha: YYYY-MM-DD
  estado: vigente | en-curso | pendiente
  ---
  ```
- Conectar con notas existentes usando `[[wiki]]` y agregar el enlace en
  `MOC - MegaG.md`.
- Diagramas en bloques ```mermaid (Obsidian los renderiza nativo).
- Si una nota crece demasiado, **dividirla** antes de que mezcle temas — no
  reincorporar contenido a este `CLAUDE.md`.

## Herramientas ECC (asistencia, opcional)

En `.claude/` hay agentes y comandos de ECC instalados (perfil `minimal`, sin
hooks: nada se ejecuta solo, no compiten con las rutinas del vault). Úsalos bajo
demanda; no son obligatorios para ninguna tarea.

- Agentes útiles aquí: `python-reviewer`, `fastapi-reviewer` (dashboard),
  `security-reviewer` (sobre todo lo que toque `secrets/`, Gmail o Drive),
  `database-reviewer` (SQLite), `code-reviewer`, `silent-failure-hunter`.
- Comandos: `/plan`, `/code-review`, `/python-review`, `/fastapi-review`,
  `/security-scan`, `/test-coverage`, `/refactor-clean`, `/build-fix`.
