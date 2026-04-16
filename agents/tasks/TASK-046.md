# TASK-046: Scroll fix en panel lateral (backtest + strategy panels)

- **ID**: TASK-046
- **Priority**: P2
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: —
- **Blocks**: —

## Files to read

- `agents/felix.md` — tu definición de rol y workflow
- `gui_charts.py` — leer antes de editar:
  - `.tv-backtest-panel` CSS (~L3556 — verificar número exacto antes de editar)
  - `#tv-strategy-panel` CSS — verificar si falta `overflow-y`
  - `.tv-side-list` scrollbar webkit styles (~L3154–3179) — bloque de referencia a copiar
  - `.tv-backtest-trades-wrapper` y `.tv-backtest-strategy-checks` — verificar que sub-scrollers internos no se rompen al añadir overflow al contenedor padre

## Description

Añadir `overflow-y: auto` (con scrollbar webkit personalizada) a los paneles laterales que se desbordan cuando el contenido crece. Bug concreto: tab Backtest con backtest largo muestra contenido que se desborda fuera del panel sin barra de desplazamiento.

## Technical context

- El fix es puramente CSS — sin cambios JS ni Python
- El bloque de scrollbar webkit en `.tv-side-list` (líneas ~3154–3179) es el patrón establecido a reutilizar
- Los sub-scrollers internos (`.tv-backtest-trades-wrapper`, `.tv-backtest-strategy-checks`) ya tienen su propio overflow — verificar que no crea scroll anidado problemático
- Este fix no depende de TASK-045 ni de ninguna otra tarea activa — puede ejecutarse inmediatamente

## Acceptance criteria

- [ ] `overflow-y: auto` añadido a `.tv-backtest-panel`
- [ ] Scrollbar webkit personalizada copiada para `.tv-backtest-panel` (mismo estilo que `.tv-side-list`)
- [ ] `#tv-strategy-panel` verificado: si falta `overflow-y`, añadirlo también
- [ ] Sub-scrollers internos (`.tv-backtest-trades-wrapper`, `.tv-backtest-strategy-checks`) no rotos — verificado leyendo el CSS existente antes de editar
- [ ] Sin cambios fuera del bloque CSS (sin tocar JS ni Python)
- [ ] Verificación manual: abrir GUI → tab Backtest → ejecutar backtest con muchos trades → scrollbar aparece y funciona
