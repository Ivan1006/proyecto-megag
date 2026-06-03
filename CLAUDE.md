# Agente Generador de Proyectos Agropecuarios

## Propósito

Sistema multi-agente que monitorea una bandeja de **Gmail corporativo**, extrae información de los correos y sus adjuntos, valida los datos contra reglas de negocio y genera la **Solicitud de Crédito Agropecuario** oficial de Bancolombia/Finagro como entregables en **Excel** y **PDF**.

El operador humano (asesor de Bancolombia) recibe el formulario rellenado y solo debe firmar y verificar. Si el correo viene incompleto, el agente detecta los faltantes y prepara una respuesta para solicitar la información que falta.

## Tipos de archivos que se pueden encontrar adjuntos en el correo

- Cámara y comercio
- Estados financieros
- Carta de certificación de insumos / fuentes de recursos
- RUT
- Declaración de renta

## Arquitectura

Tres agentes orquestados con **LangGraph**:

```
correo + adjuntos
       │
       ▼
[Agente 1] Ingesta y extracción
   ├─ Monitor Gmail (OAuth2)
   ├─ Descarga cuerpo + adjuntos
   ├─ Parsers PDF / Excel / Word / OCR imágenes
   └─ Mapeo correo → campos (LLM OpenAI)
       │
       ▼
[Agente 2] Validación y reglas
   ├─ Motor de reglas (config/rules.yaml)
   ├─ Validador de campos (regex, rangos, valores permitidos)
   ├─ Gestor de brechas (faltantes, formato inválido)
   └─ ¿Aprobado? ──► Sí ──► Agente 3
                  └─ No ──► Notificar al remitente (texto redactado)
       │
       ▼
[Agente 3] Generación
   ├─ code_resolver — sub-agente LLM que consulta el Anexo Finagro y
   │   asigna cod_destino + descripción para la tabla de actividades
   ├─ Enricher — totales tabla, cronograma fechas
   ├─ Excel writer — abre el template oficial y rellena celdas
   └─ PDF writer — convierte el Excel rellenado vía LibreOffice headless
       │
       ▼
   Excel + PDF (Solicitud Crédito Agropecuario rellenada)
       │
       ▼
   Almacenamiento Google Drive + notificación
```

## Stack

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.11+ |
| Orquestación multi-agente | LangGraph + LangChain |
| LLM | OpenAI (GPT-4o, GPT-4o-mini) |
| Bandeja | Gmail API (OAuth2) |
| Almacenamiento final | Google Drive API |
| Modelos de datos | Pydantic v2 + pydantic-settings |
| Parsers | pdfplumber, openpyxl, xlrd, python-docx, pytesseract |
| Generación Excel | openpyxl (rellena template oficial) |
| Generación PDF | LibreOffice headless (`soffice --convert-to pdf`) |
| Persistencia | SQLite (idempotencia por `message_id`) |
| CLI | Typer + Rich |
| Logging | structlog |

## Estructura del repositorio

```
proyecto_megag/
├── pyproject.toml               # deps (instalable con pip install -e .)
├── .env.example                 # OPENAI_API_KEY, rutas, filtros Gmail
├── claude.md                    # este archivo
├── README.md
├── arquitectura_agropecuario.drawio
│
├── config/
│   ├── rules.yaml               # campos requeridos/opcionales, rangos, regex
│   ├── excel_cells.yaml         # mapeo campo → celda en el template
│   ├── defaults.yaml            # valores hardcoded (BANCOLOMBIA, oficina)
│   ├── template.yaml            # plantilla legacy (en deshuso post sub-fase 1.A)
│   └── catalogo_destinos.xlsx   # Anexo Finagro: 1129 códigos destino/producto
│
├── templates/
│   ├── credito_agro_template.xlsx   # formulario oficial Bancolombia/Finagro
│   ├── proyecto.html.j2             # legacy (no usado en flujo Finagro)
│   └── proyecto.css                 # legacy
│
├── data/
│   ├── samples/credito_demo.json    # datos de ejemplo para fill-template
│   ├── tmp/                         # adjuntos descargados de Gmail
│   └── output/                      # Excel + PDF generados
│
├── secrets/
│   ├── client_secret.json           # OAuth desktop client (no versionar)
│   └── token.json                   # token cacheado tras `agropecuario auth`
│
├── src/agropecuario/
│   ├── __init__.py
│   ├── settings.py                  # pydantic-settings, lee .env
│   ├── logging_conf.py              # structlog
│   ├── models.py                    # contratos Pydantic entre agentes
│   ├── orchestrator.py              # build_graph() LangGraph
│   ├── cli.py                       # Typer: auth, run, watch, list-messages,
│   │                                #        extract-local, extract-gmail,
│   │                                #        fill-template
│   ├── agents/                      # nodos LangGraph
│   │   ├── state.py                 # TypedDict del grafo
│   │   ├── ingesta.py
│   │   ├── validacion.py            # nodo validar + nodo notificar
│   │   └── generacion.py            # *legacy en proceso de actualización*
│   ├── ingesta/
│   │   ├── gmail_client.py          # OAuth, list_messages, fetch_message
│   │   ├── extractor.py             # combina cuerpo + adjuntos
│   │   └── parsers/
│   │       ├── pdf_parser.py
│   │       ├── excel_parser.py      # .xlsx (openpyxl) + .xls (xlrd)
│   │       ├── word_parser.py
│   │       └── image_parser.py      # OCR Tesseract (req: tesseract-ocr-spa)
│   ├── validacion/
│   │   ├── rule_engine.py           # carga rules.yaml
│   │   ├── validator.py             # aplica reglas sobre dict de campos
│   │   └── gap_manager.py           # construye ValidationResult + draft reply
│   ├── generacion/
│   │   ├── template_engine.py       # legacy (carga template.yaml)
│   │   ├── mapper.py                # LLM correo → campos *prompt legacy*
│   │   ├── enricher.py              # cálculos + secciones LLM *legacy*
│   │   ├── excel_writer.py          # rellena credito_agro_template.xlsx
│   │   └── pdf_writer.py            # LibreOffice headless
│   └── storage/
│       ├── temp_store.py            # SQLite (escrito, no cableado al grafo)
│       └── drive_client.py          # sube entregables a Drive
│
└── tests/
    ├── test_models.py
    ├── test_rules.py
    └── test_template.py
```

## Estado actual del proyecto

### Sub-fase 1.A — completada ✅

**Objetivo**: rellenar el formulario oficial Bancolombia/Finagro con datos JSON sintéticos y generar Excel + PDF idénticos al template.

Lo que ya funciona:

- `agropecuario fill-template --data data/samples/credito_demo.json`
  - Abre `templates/credito_agro_template.xlsx`
  - Aplica defaults (BANCOLOMBIA, oficina principal)
  - Rellena 50+ celdas según `config/excel_cells.yaml`
  - Preserva fórmulas `=SUM(...)` (los totales de la tabla se recalculan solos)
  - Maneja celdas combinadas (escribe en la esquina superior-izquierda)
  - Marca con "X" las opciones de tipo de beneficiario, tenencia, FAG sí/no
  - Manejo especial del **tipo de identificación**: marca X en la fila correspondiente (CC/NIT/CE) y escribe el número solo en esa fila
  - **Códigos por dígito**: distribuye un código tipo `0127` en celdas individuales (`N57=0`, `O57=1`, `P57=2`, `Q57=7`)
  - Sección 10 (firma del funcionario verificador) **se deja en blanco** intencionalmente
  - Convierte el Excel rellenado a PDF con LibreOffice headless preservando el layout exacto

### Conexión Gmail — completada ✅

- OAuth2 funcionando (`agropecuario auth` ya ejecutado)
- Token cacheado en `secrets/token.json`
- Comandos disponibles:
  - `agropecuario list-messages` — lista correos según filtro
  - `agropecuario extract-gmail [-m <id>]` — descarga correo, parsea adjuntos, mapea con LLM
  - `agropecuario extract-local --file <path>` — prueba parsers sobre archivos locales (sin Gmail)

### Configuración del entorno

- LibreOffice 24.2.7.2 instalado y funcionando
- `OPENAI_API_KEY` configurada en `.env`
- Filtro Gmail por defecto: `is:unread` (configurable en `.env` con `GMAIL_QUERY_FILTER`)
- Cuentas de prueba registradas en consola Google Cloud (modo Testing)

## Decisiones técnicas relevantes

### ¿Por qué rellenar el template en lugar de regenerar el Excel?

El formulario Bancolombia/Finagro tiene un layout muy específico (celdas combinadas, fórmulas, estilos, márgenes para impresión). Reproducirlo desde cero con `xlsxwriter` o Jinja sería frágil y costoso. Abriendo el template con `openpyxl` y escribiendo en celdas con `_set()` que respeta merges, preservamos formato perfecto.

### ¿Por qué LibreOffice headless para PDF?

WeasyPrint exigiría reimplementar el formulario en HTML/CSS pixel-perfect. LibreOffice ya sabe convertir el Excel oficial a PDF preservando el layout. `soffice --headless --convert-to pdf` corre en ~250 ms.

### Configuración como código vs. configuración como datos

Las celdas, defaults, reglas y plantilla del proyecto viven en `config/*.yaml`. Cualquier cambio del formulario Bancolombia, ajuste de validaciones o nuevo campo se hace **sin tocar Python** — esencial porque los analistas de negocio iterarán sobre las reglas más rápido que el ciclo de despliegue.

### Idempotencia por `message_id`

`storage/temp_store.py` usa `message_id` de Gmail como UNIQUE en SQLite. Reprocesar el mismo correo es no-op a menos que cambie el estado explícitamente. Evita duplicados al reiniciar el `watch`.

### Sub-agente `code_resolver` (próximo)

La sección 5 del formulario (tabla de actividades a financiar) requiere asignar `cod_línea + cod_rubro + descripción` consultando el catálogo Finagro de 1129 entradas. Esto NO viene explícito en el correo: el agente debe inferir el código a partir de la actividad del cliente y el destino del crédito. Estrategia planeada: dos pasos LLM — primero acotar por categoría macro (Producción / Comercialización / Inversión / etc.), luego elegir el código específico dentro del subset filtrado.

## Cómo usar el sistema

### Instalación

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env       # editar OPENAI_API_KEY
```

### Probar generación de entregables (sin Gmail, sin LLM)

```bash
agropecuario fill-template --data data/samples/credito_demo.json
# → data/output/credito_demo.xlsx
# → data/output/credito_demo.pdf
```

### Probar conexión Gmail (sin LLM)

```bash
agropecuario list-messages --limit 5
agropecuario extract-gmail --no-llm
```

### Probar extracción completa (Gmail + LLM)

```bash
agropecuario extract-gmail -m <message-id>
```

### Tests determinísticos

```bash
pytest -v
```

---

## Tareas pendientes

### 1. Módulo `catalogo/` + sub-agente `code_resolver`

Implementar `src/agropecuario/catalogo/loader.py` para cargar `config/catalogo_destinos.xlsx` (1129 filas) en una estructura indexable, y `code_resolver.py`: sub-agente LLM que recibe la actividad del cliente + destino del crédito y devuelve los códigos exactos (`cod_línea`, `cod_rubro`, descripción del rubro, producto relacionado, plazo, línea de crédito) que rellenan la **tabla de actividades de la sección 5** del formulario. Estrategia recomendada: 2 pasos LLM (categoría macro → código específico) para evitar saturar el contexto con las 1129 entradas.

### 2. Reescribir `mapper.py` con prompt para campos Finagro

El prompt actual extrae campos genéricos (`productor_nombre`, `cultivo`). Reescribirlo para extraer los campos del formulario Bancolombia: `beneficiario_razon_social`, `beneficiario_id_tipo`, `beneficiario_id_numero`, `beneficiario_direccion`, `tipo_beneficiario`, `predio_*`, `tenencia`, `forma_de_llegar`, `justificacion_tecnica`, `modalidad_pago_capital`, `modalidad_pago_intereses`, `actividad_economica_descripcion`, `garantia_fag`, etc. — todos los campos definidos en `rules.yaml`. La asignación de **códigos** queda fuera del mapper (la maneja `code_resolver`).

### 3. Actualizar `enricher.py` con cálculos del formulario

Reemplazar los cálculos genéricos actuales (`monto_por_hectarea`, cronograma de cuotas) por los específicos del formulario Finagro: validar que las sumas de la tabla de actividades cuadren con las fórmulas `=SUM(I49:I52)` y `=SUM(J49:K52)`, calcular fechas del cronograma de inversión (inicial/final) a partir del plazo + período de gracia, y producir el dict final que se pasa a `excel_writer.render_excel()`. Cablear todo este flujo al grafo LangGraph (actualizar `agents/generacion.py`) para que `agropecuario run -m <id>` haga el end-to-end correo → Excel + PDF Finagro.

## Notas del proyecto

## Notas en mi vault de Obsidian

Cuando documentes decisiones, avances, ideas o aprendizajes del proyecto,
escríbelos en mi vault en `/home/ivan1006/Documents/proyecto-megag`.

- Crea una nota por tema, con nombre descriptivo.
- Usa frontmatter YAML con `tags`, `fecha` y `estado`.
- Conecta notas relacionadas con enlaces [[wiki]].
- Mantén actualizada una nota índice "MOC - MiProyecto.md" que enlace a todo.
- Para diagramas usa bloques ```mermaid (se renderizan nativos en Obsidian).
