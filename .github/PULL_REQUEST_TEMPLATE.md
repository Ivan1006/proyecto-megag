## Resumen

<!-- 1-3 frases describiendo el cambio. Qué hace, no cómo. -->

## Tipo de cambio

- [ ] `feat` — Nueva funcionalidad
- [ ] `fix` — Corrección de bug
- [ ] `refactor` — Cambio interno sin afectar comportamiento
- [ ] `docs` — Solo documentación
- [ ] `chore` — Mantenimiento (deps, configs, CI)
- [ ] `breaking` — Cambio incompatible (marca también arriba)

## Tickets relacionados

Closes #
Related to #

## Cambios principales

<!-- Bullets con los cambios técnicos relevantes. -->
- 
- 

## Cómo probarlo

<!-- Pasos concretos para validar el cambio localmente. -->

```bash
# ejemplo
agropecuario process-thread <thread_id>
```

## Capturas / GIFs (si aplica UI)

<!-- Antes / después. -->

## Checklist

- [ ] Probé el cambio localmente (golden path + al menos 1 caso de error).
- [ ] Añadí o actualicé tests.
- [ ] `ruff check src/ tests/` pasa.
- [ ] `pytest` pasa.
- [ ] Actualicé documentación afectada (README / docstrings / docs/).
- [ ] No commiteé secretos ni archivos generados (`data/`, `*.sqlite`, `.env`).
- [ ] El PR está dirigido a `develop` (o a `main` si es hotfix).

## Notas para el revisor

<!-- Áreas de duda, decisiones de diseño, contexto que ayude a revisar. -->
