# Cómo contribuir

Gracias por contribuir al proyecto. Esta guía describe cómo trabajamos en el día a día: ramas, commits, PRs, estilo de código y tests.

---

## TL;DR

1. Crea una rama desde `develop` (no desde `main`).
2. Sigue la convención de nombres: `feature/<ticket>-<descripcion-corta>`.
3. Commits en formato **Conventional Commits** (`feat:`, `fix:`, `chore:`…).
4. Abre el PR contra `develop`. Mínimo 1 revisor.
5. CI verde antes de merge. Squash & merge.

---

## Estrategia de ramas (GitFlow simplificado)

```
main         ●───●─────●───────────●──────▶  (producción, deploy)
              \   \     \           \
release/*      ●   ●     ●           ●
              /   /     /           /
develop  ───●───●─────●───────────●──────▶  (integración, default)
            \   \    /\           /
feature/*    ●───●───● ●──────────●
                              ↑
                       hotfix/* desde main
```

### Ramas permanentes

| Rama | Propósito | Protección |
|------|-----------|------------|
| `main` | Código en producción. Siempre desplegable. | ❌ No push directo. Solo merge desde `release/*` o `hotfix/*`. |
| `develop` | Rama de integración. Default branch. | ❌ No push directo. Solo merge vía PR aprobado. |

### Ramas temporales

| Prefijo | Origen | Destino | Cuándo usar |
|---------|--------|---------|-------------|
| `feature/<n>-<slug>` | `develop` | `develop` | Nueva funcionalidad o mejora no crítica. |
| `bugfix/<n>-<slug>` | `develop` | `develop` | Bug que no es urgente en producción. |
| `hotfix/<n>-<slug>` | `main` | `main` + `develop` | Bug crítico en producción. |
| `release/x.y.z` | `develop` | `main` + `develop` | Preparar un release (bump de versión, changelog, QA final). |
| `chore/<slug>` | `develop` | `develop` | Tareas de mantenimiento (deps, configs, CI). |
| `docs/<slug>` | `develop` | `develop` | Solo cambios de documentación. |
| `experiment/<slug>` | `develop` | (descartable) | Pruebas exploratorias. No se mergea. |

### Nombres recomendados

```bash
feature/14-code-resolver-agent
bugfix/231-fix-thread-aggregation-tz
hotfix/342-gmail-upload-timeout
release/0.3.0
chore/bump-langchain-0.3
docs/update-branching-guide
```

Reglas:

- Slug en `kebab-case`, en inglés o español pero consistente por rama.
- Si hay ticket asociado, va al principio (`feature/14-…`).
- Sin espacios, sin mayúsculas, sin caracteres especiales.

---

## Flujo de trabajo

### Iniciar una feature

```bash
git checkout develop
git pull --rebase origin develop
git checkout -b feature/14-code-resolver-agent
```

### Mantener la rama al día

Reabasea (no merge) sobre `develop` con frecuencia:

```bash
git fetch origin
git rebase origin/develop
```

Si hay conflictos, resuélvelos localmente. **No** uses `merge develop` dentro de la feature — ensucia el historial.

### Abrir el PR

- Target: `develop` (siempre, salvo hotfix).
- Título: igual que el primer commit (`feat: resolver de códigos Finagro`).
- Descripción: usa la plantilla `.github/PULL_REQUEST_TEMPLATE.md`.
- Asigna 1 revisor mínimo.
- Etiquetas: `feature`, `bug`, `docs`, `chore`, `breaking`.

### Merge

- **Squash & merge** por defecto. Un PR = un commit en `develop`.
- El mensaje del squash sigue Conventional Commits.
- Si el PR contiene varios commits lógicamente independientes (raro), usar **Rebase & merge**.
- **Nunca** "Create a merge commit" en `develop` — ensucia el historial.

### Release

```bash
git checkout develop
git pull
git checkout -b release/0.3.0

# 1) Bump de versión en pyproject.toml
# 2) Actualizar CHANGELOG.md
# 3) QA final, smoke tests

git checkout main
git merge --no-ff release/0.3.0
git tag -a v0.3.0 -m "Release 0.3.0"
git push origin main --tags

git checkout develop
git merge --no-ff release/0.3.0
git push origin develop

git branch -d release/0.3.0
git push origin --delete release/0.3.0
```

### Hotfix

```bash
git checkout main
git checkout -b hotfix/342-gmail-upload-timeout

# fix + test

git checkout main && git merge --no-ff hotfix/342-gmail-upload-timeout
git tag -a v0.3.1 -m "Hotfix Gmail timeout"
git push origin main --tags

git checkout develop && git merge --no-ff hotfix/342-gmail-upload-timeout
git push origin develop
```

---

## Convención de commits (Conventional Commits)

```
<tipo>(<scope opcional>): <descripción imperativa, sin punto final>

[cuerpo opcional]

[footer opcional]
```

### Tipos

| Tipo | Cuándo |
|------|--------|
| `feat` | Nueva funcionalidad para el usuario. |
| `fix` | Corrección de bug. |
| `docs` | Solo documentación. |
| `style` | Formato, espacios, comas — sin cambio de lógica. |
| `refactor` | Refactor sin cambiar comportamiento. |
| `perf` | Mejora de rendimiento. |
| `test` | Añadir o corregir tests. |
| `build` | Build, dependencias (`pyproject.toml`, lockfiles). |
| `ci` | Configuración de CI/CD. |
| `chore` | Otros (renombres, limpieza). |
| `revert` | Revertir un commit anterior. |

### Ejemplos

```
feat(ingesta): agregar trigger por etiqueta "bot"

Permite al analista disparar el procesamiento aplicando la etiqueta `bot`
en Gmail. El watcher excluye los hilos con `bot-procesado` para evitar
reproceso. Closes #18.
```

```
fix(aggregator): conservar timezone al ordenar mensajes

Antes ordenaba por string naive, lo que rompía cuando los correos venían
de distintos husos. Ahora se parsea con `datetime.fromisoformat` y se
normaliza a UTC.
```

```
chore(deps): bump langchain a 0.3.x
```

### Breaking changes

Añadir `!` después del tipo o `BREAKING CHANGE:` en el footer:

```
feat(api)!: cambiar firma de process_thread

BREAKING CHANGE: process_thread ahora recibe EmailThread en vez de thread_id.
Los llamadores deben construir el thread antes.
```

---

## Estilo de código

- **Formato**: `ruff format` (sigue `pyproject.toml`).
- **Lint**: `ruff check src/ tests/` debe pasar.
- **Tipos**: `mypy src/` debe pasar en modo estricto en módulos nuevos.
- **Docstrings**: Google style en funciones públicas. Internos solo si el nombre no es suficiente.
- **Imports**: ordenados (ruff `I`). Sin imports relativos profundos.
- **Pydantic**: v2 en todo modelo nuevo.

---

## Tests

- Cada feature debe traer su test.
- Bug fix → test que reproduce el bug **antes** de la corrección.
- `pytest -m "not slow"` para iteración rápida.
- Cobertura objetivo: 80%+ en módulos críticos (`validacion/`, `ingesta/`, `runner.py`).

```bash
pytest                   # todo
pytest -k aggregator     # por keyword
pytest --cov=agropecuario --cov-report=term-missing
```

---

## Seguridad

- **Nunca** commitear `.env`, `secrets/`, `*.json` con tokens.
- Si por accidente subes una credencial: rotarla inmediatamente y abrir issue.
- Las dependencias se auditan con `pip-audit` antes de cada release.

---

## Code review — qué buscar

- ¿Las funciones tienen una responsabilidad clara?
- ¿Hay tests para el camino feliz y al menos un caso de error?
- ¿Los nombres explican la intención?
- ¿Se evitan side-effects ocultos (lectura de archivos, llamadas de red sin inyección)?
- ¿El cambio respeta los contratos Pydantic existentes?
- ¿Documentación actualizada (README / docstrings) si la API pública cambió?

---

## Dudas

Abre un issue con la etiqueta `question` o pregunta en el canal del equipo.
