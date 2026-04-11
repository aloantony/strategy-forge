# TASK-033: Export de resultados de backtest a CSV

- **ID**: TASK-033
- **Priority**: P3
- **Status**: todo
- **Assigned**: Felix
- **Blocked by**: TASK-031
- **Blocks**: nada

## Files to read
- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `gui_charts.py` — leer los rangos del tab Backtest indicados abajo; Grace NO produce spec para esta tarea (es un cambio directo, cosmético y bien delimitado)

## Description

Añadir un botón "Exportar CSV" en la sección de resultados del tab Backtest. Al hacer clic, genera y descarga un archivo CSV con la lista de trades individuales del backtest más reciente. El export ocurre completamente en el lado Python (no en JS) para evitar problemas con los permisos del webview para acceso a sistema de archivos.

Esta es la única tarea del sprint de Backtest GUI que Felix puede implementar en "direct mode" (sin spec de Grace), porque:
- Es un cambio de un único punto de inserción: un botón en el panel de resultados
- La acción resultante es un callback JS → Python que escribe un archivo
- No introduce nuevos elementos DOM complejos ni nuevas secciones

## Technical context

- Relevant files: `gui_charts.py`
- Relevant sections:
  - Líneas 4425–4594: `renderBacktestPanel` — donde se añade el botón "Exportar CSV" en la sección de resultados (después de las cards, dentro del bloque `if (!state.result || ...)`)
  - `on_side_panel_event` (línea ~4209): donde se añade el handler para el evento `backtest_export_csv`
- Patrón de callback existente: `window.callbackFunction(state.handler + "_~_backtest_export_csv")` — Felix sigue el mismo patrón que `backtest_run`
- El Python handler recibe el resultado actual de `self.backtest_state["result"]`, extrae la lista `trades`, y escribe un CSV usando `csv` de la stdlib en `~/Downloads/backtest_<strategy>_<symbol>_<timestamp>.csv`
- Columnas del CSV: id, entry_time (ISO), exit_time (ISO), direction, entry_price, exit_price, volume, profit, reason, signal, signal_reason, mode

## Acceptance criteria
- [ ] Botón "Exportar CSV" visible en la sección de resultados solo cuando hay un resultado exitoso
- [ ] Al hacer clic, se genera un archivo CSV en `~/Downloads/` con nombre descriptivo
- [ ] CSV contiene las columnas especificadas arriba, una fila por trade
- [ ] Si no hay resultado disponible, el botón está deshabilitado o no visible
- [ ] No se rompe ninguna funcionalidad existente del tab Backtest
- [ ] El archivo se crea correctamente en Windows (paths con `pathlib.Path.home() / "Downloads"`)
- [ ] El usuario recibe feedback visual (mensaje de estado actualizado) indicando que el export fue exitoso o fallido
