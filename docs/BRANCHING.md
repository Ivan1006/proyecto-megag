# Estrategia de ramas

Documento de referencia rápida sobre cómo organizamos el repositorio. Para el flujo completo de contribución ver [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Modelo: GitFlow simplificado

Elegimos **GitFlow simplificado** (no GitHub Flow puro, no GitFlow completo) porque:

- Tenemos un dashboard en producción + cambios frecuentes en código LLM y reglas.
- Necesitamos poder hacer **hotfixes** sin esperar el próximo release.
- Pero no necesitamos `support/*` ni ramas de mantenimiento de versiones antiguas.

```
                 ╔═══════════════════════════════════════════╗
                 ║                                           ║
   main      ●───╫───●─────●─────────────●─────────────●─────╫─▶  prod
              \  ║    \     \             \             \    ║
   release/*   ● ║     ●     ●             ●             ●   ║   estabilización
              / ║    /     /             /             /     ║
   develop  ●─●─╫───●─────●─────────────●─────────────●──────╫─▶  integración
            \  ║  /  \   /  \         /              /        ║
   feature/* ● ║ ●    ● ●    ●───────●              ●         ║
              ║                                               ║
              ║      hotfix/*   ●                             ║
              ║                 │                             ║
              ║    main ●───────┘─▶ ●  ─→ vuelve a develop    ║
              ╚═══════════════════════════════════════════════╝
```

---

## Ramas a crear inicialmente

Cuando setees el repo por primera vez, crea estas dos:

```bash
# Asumiendo que ya hiciste el push inicial a main
git checkout -b develop
git push -u origin develop

# Establecer develop como default branch en GitHub:
# Settings → Branches → Default branch → develop
```

Y proteger ambas:

| Rama | Reglas de protección |
|------|---------------------|
| `main` | ✅ Require PR before merge. ✅ Require status checks (CI). ✅ Require linear history. ❌ No force push. ❌ No delete. |
| `develop` | ✅ Require PR before merge. ✅ Require status checks (CI). ❌ No force push. ❌ No delete. |

---

## Inventario completo de tipos de ramas

| Prefijo | Origen | Destino | Vida | Ejemplo |
|---------|--------|---------|------|---------|
| `main` | — | — | permanente | `main` |
| `develop` | — | — | permanente | `develop` |
| `feature/` | `develop` | `develop` | hasta merge | `feature/14-code-resolver-agent` |
| `bugfix/` | `develop` | `develop` | hasta merge | `bugfix/231-tz-aggregation` |
| `hotfix/` | `main` | `main` + `develop` | hasta merge | `hotfix/342-drive-timeout` |
| `release/` | `develop` | `main` + `develop` | hasta release | `release/0.3.0` |
| `chore/` | `develop` | `develop` | hasta merge | `chore/bump-langchain` |
| `docs/` | `develop` | `develop` | hasta merge | `docs/branching-update` |
| `experiment/` | `develop` | (descarte) | indefinida | `experiment/new-llm-prompt` |

---

## Reglas de protección por rama (GitHub UI)

### `main`
- ✅ Require a pull request before merging
  - ✅ Require approvals: **1** mínimo (2 si el equipo crece)
  - ✅ Dismiss stale approvals when new commits are pushed
  - ✅ Require review from Code Owners (si se define `CODEOWNERS`)
- ✅ Require status checks to pass before merging
  - ✅ Require branches to be up to date
  - Checks requeridos: `lint`, `tests`
- ✅ Require linear history
- ✅ Require signed commits (opcional, recomendado)
- ❌ Allow force pushes
- ❌ Allow deletions

### `develop`
- ✅ Require a pull request before merging
  - ✅ Require approvals: **1**
- ✅ Require status checks to pass before merging
  - Checks requeridos: `lint`, `tests`
- ❌ Allow force pushes
- ❌ Allow deletions

---

## Versionado

Seguimos **SemVer** (`MAJOR.MINOR.PATCH`):

- `MAJOR` — cambios incompatibles en la API pública (signatures, contratos Pydantic, esquema SQLite).
- `MINOR` — nueva funcionalidad backwards-compatible.
- `PATCH` — bug fixes.

Las versiones se taggean en `main`:

```bash
git tag -a v0.3.0 -m "Release 0.3.0 — Code resolver Finagro"
git push origin v0.3.0
```

---

## Cuando algo se complica

| Situación | Qué hacer |
|-----------|-----------|
| "Mi feature depende de otra que aún no se mergea" | Crea tu rama desde la otra feature en vez de `develop`. Documenta en el PR la dependencia. |
| "Necesito un hotfix pero la rama `release/*` está abierta" | Hotfix sigue saliendo de `main`. Después del merge, también se mergea en `release/*` para no perderlo en QA. |
| "Conflicto al rebasear" | Rebase, no merge. Resuelve y `git rebase --continue`. Si es muy grande, abre el debate en el PR. |
| "Mergeé a `develop` sin querer" | Revert con `git revert -m 1 <merge-sha>` y reabrir el PR limpio. **No** force-push. |
| "Subí una credencial" | Rotala inmediatamente, abre issue de seguridad, y limpia el historial con `git filter-repo` (no `filter-branch`). |
