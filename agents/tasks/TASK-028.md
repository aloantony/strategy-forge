# TASK-028: Spec GUI — tabla de trades, equity curve y drawdown en tab Backtest

- **ID**: TASK-028
- **Priority**: P1
- **Status**: todo
- **Assigned**: Grace
- **Blocked by**: TASK-027
- **Blocks**: TASK-031

## Files to read
- `agents/grace.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-027-backtest-result-extension.md` — campos exactos que el backend retornará (equity_curve, drawdown_curve, trades list, nuevas métricas)
- `gui_charts.py` — leer SOLO los rangos relevantes al tab Backtest:
  - líneas 699–924: Python handlers del backtest (`_get_backtest_payload`, `_render_backtest_panel`, `_on_backtest_run`)
  - líneas 3197–3330: CSS del panel backtest (`.tv-backtest-*` clases)
  - líneas 4425–4594: JS `window.renderBacktestPanel` — la función de render completa, incluyendo las cards de resultados actuales
  - líneas 7025–7080: `update_equity_chart` — patrón del sub-chart de equity del bot en vivo (referencia de cómo funciona `self.equity_line.set(df)`)

## Description

Actualmente el tab Backtest muestra 8 cards de resumen (balance final, profit, retorno %, operaciones, win rate, max DD, rango, TF). Con la extensión de TASK-027, el backend retornará datos completos de trades individuales, equity curve por vela y drawdown curve. Grace debe diseñar y especificar cómo añadir estas tres secciones visuales al panel existente **sin romper** el formulario ni las cards actuales.

## Technical context

- Relevant files: `gui_charts.py`
- Relevant sections: ver "Files to read" arriba
- El panel backtest se renderiza íntegramente desde JS en `window.renderBacktestPanel` (línea ~4425), que recibe un `payload` dict serializado via `json.dumps` desde Python. Felix no modifica Python a menos que Grace lo indique explícitamente.
- El panel vive dentro del side panel (`tv-side-panel`) — ancho fijo limitado (~280–320px). Diseño en columna, sin espacio para gráficos de gran tamaño.
- Los sub-charts del bot en vivo (`equity_chart`, `tci_chart`) son charts de `lightweight_charts` creados en `__init__` como `chart.create_subchart(...)`. El tab Backtest es un panel HTML, NO un sub-chart lightweight_charts. Esto significa que la "equity curve visual" debe ser un elemento SVG/Canvas inline en el HTML del panel, NO un sub-chart de lightweight_charts. Grace debe decidir la tecnología de renderizado (SVG path, Canvas 2D) y especificarla.
- El threading model del panel Backtest es: el worker thread llama `self._render_backtest_panel()` desde `_run_backtest_worker`, que ejecuta directamente `chart.run_script(...)`. Esto está fuera del callback_queue — es un patrón ya establecido en el código existente y Grace no debe cambiarlo.
- Restricción de tamaño: `equity_curve` y `drawdown_curve` pueden ser grandes. Grace debe especificar si `_render_backtest_panel` los incluye en el payload completo o si se disparan por separado (segundo `run_script`).

## What Grace must produce

Un spec en `agents/specs/TASK-028-backtest-gui-spec.md` que incluya:

1. **Mapa de inserción**: qué añadir en el HTML del panel (sección de tabla de trades, sección de equity chart, sección de drawdown), con IDs de elementos nuevos y su posición relativa al DOM existente.
2. **CSS nuevo**: clases necesarias para tabla de trades, micro-chart de equity y micro-chart de drawdown. Integrado en el bloque CSS existente del backtest (cerca de línea 3197).
3. **JS nuevo en `renderBacktestPanel`**: pseudocode/código exacto para:
   - Renderizar la tabla de trades (columnas: #, Tipo, Entrada, Salida, Precio entrada, Precio salida, P&L, Razón)
   - Renderizar el micro-chart de equity (SVG path o Canvas 2D — Grace elige y justifica)
   - Renderizar el micro-chart de drawdown
4. **Puntos de inserción exactos** en `gui_charts.py`: número de línea de inicio del bloque donde Felix inserta cada fragmento. Tolerancia ±5 líneas indicada como nota.
5. **Cambios en Python** (si necesarios): si `_render_backtest_panel` debe incluir o excluir campos del payload. Si `_get_backtest_payload` necesita cambios.
6. **Decisión sobre el payload**: ¿se envían `equity_curve` y `drawdown_curve` en el mismo `run_script` que el panel, o en un segundo `run_script` separado post-render? Justificación de la decisión.

## Acceptance criteria
- [ ] Spec existe en `agents/specs/TASK-028-backtest-gui-spec.md`
- [ ] Spec define DOM completo de cada nueva sección (IDs, clases, jerarquía de elementos)
- [ ] Spec especifica tecnología de renderizado del micro-chart (SVG o Canvas) con justificación
- [ ] Spec incluye CSS completo para todas las clases nuevas
- [ ] Spec incluye pseudocode/código JS detallado para tabla de trades y ambos micro-charts
- [ ] Spec indica puntos de inserción exactos (línea ± 5) en `gui_charts.py`
- [ ] Spec no introduce patrones de threading distintos a los ya establecidos
- [ ] Columnas de la tabla de trades: #, Tipo, Hora entrada, Hora salida, P. entrada, P. salida, P&L, Razón
