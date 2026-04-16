# TASK-047: Micro-interacciones, animaciones y spinner en botones

- **ID**: TASK-047
- **Priority**: P2
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-045
- **Blocks**: —

## Files to read

- `agents/felix.md` — tu definición de rol y workflow
- `agents/specs/TASK-045-gui-polish-spec.md` — spec de Grace: inventario de botones, valores de transition/scale, cambio del tab switcher, selector y CSS del spinner
- `gui_charts.py` — leer la línea exacta del tab switcher JS especificada por Grace antes de editar

## Description

Implementar micro-interacciones CSS en todos los botones interactivos del GUI, el fade entre tabs (Opción B con requestAnimationFrame), y el spinner CSS en el botón de backtest mientras está en ejecución. Felix implementa siguiendo la spec de Grace — no toma decisiones de diseño propias.

## Technical context

- **Cambios CSS**: añadir `transition`, `transform: scale(0.97)` en `:active`, `box-shadow` en hover para primarios — dentro de `_inject_custom_styles()`
- **Tab fade-in (Opción B)**: cambio quirúrgico de 3 líneas en el JS del tab switcher + CSS `@keyframes tvTabFadeIn` + clase `.tv-tab-fade-in`. Usar la línea exacta que Grace especifique
- **Spinner en `#tv-backtest-run`**: CSS `@keyframes tvSpinner` + pseudo-element `::after` usando el selector que Grace especifique (`button:disabled::after` o clase). El JS de disable ya existe — Felix solo añade CSS
- Verificar que no hay flickering en el chart principal tras el cambio del tab switcher
- Verificar que el `display: none` original del tab oculto no interfiere con el keyframe del tab visible

## Acceptance criteria

- [ ] `transition` CSS aplicado a todos los selectores del inventario de Grace
- [ ] `transform: scale(0.97)` en `:active` para todos los botones del inventario
- [ ] `box-shadow` en hover para botones primarios (Run Backtest, Guardar Params)
- [ ] Tab fade-in funciona: cambiar tab muestra transición de 0.18s, sin parpadeo
- [ ] Spinner visible en `#tv-backtest-run` mientras backtest está corriendo (estado disabled)
- [ ] Spinner desaparece cuando backtest termina (botón vuelve a enabled)
- [ ] Chart principal sin flickering tras los cambios
- [ ] Cero cambios fuera de `_inject_custom_styles()` y el bloque JS del tab switcher
