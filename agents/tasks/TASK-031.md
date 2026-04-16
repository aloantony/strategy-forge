# TASK-031: Implementar tabla de trades, equity curve y drawdown en tab Backtest (single strategy)

- **ID**: TASK-031
- **Priority**: P1
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-028
- **Blocks**: TASK-033

## Files to read
- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-028-backtest-gui-spec.md` — spec a implementar verbatim; contiene puntos de inserción, CSS, JS y cambios Python
- `agents/specs/TASK-027-backtest-result-extension.md` — shape del resultado del backend (campos que llegan en el payload)
- `backtesting/runtime.py` — leer SOLO `_build_success_result` para confirmar los campos disponibles
- `gui_charts.py` — leer SOLO los rangos de línea indicados en el spec de Grace (no explorar el archivo completo)

## Description

Implementar en `gui_charts.py` los cambios especificados por Grace en TASK-028: tabla de trades individuales, micro-chart de equity curve y micro-chart de drawdown. También implementar los cambios en `backtesting/runtime.py` especificados por Daniel en TASK-027 (exposición de `equity_curve`, `drawdown_curve` y métricas adicionales en `_build_success_result`).

## Technical context

- Relevant files: `gui_charts.py`, `backtesting/runtime.py`
- `gui_charts.py` tiene ~6600 líneas — todos los cambios deben ser quirúrgicos en los puntos de inserción del spec. Sin refactoring oportunista.
- Los cambios en `backtesting/runtime.py` son los primeros cambios en ese archivo desde que se implementó el motor completo. Ser conservador: solo añadir al resultado, no modificar la lógica de simulación.
- Seguir el spec de Grace (TASK-028) verbatim — sin decisiones de diseño propias.
- Seguir el pseudocode de Daniel (TASK-027) verbatim para los cambios en `runtime.py`.
- Patrón threading ya establecido: `_render_backtest_panel` puede llamar `chart.run_script()` directamente (se invoca desde el worker thread pero este patrón ya existe).

## Acceptance criteria
- [x] `backtesting/runtime.py`: `_build_success_result` retorna `equity_curve`, `drawdown_curve` y las métricas adicionales definidas en TASK-027
- [x] `gui_charts.py`: tabla de trades individuales visible tras completar un backtest
- [x] `gui_charts.py`: micro-chart de equity curve visible tras completar un backtest
- [x] `gui_charts.py`: micro-chart de drawdown visible tras completar un backtest
- [x] Las 8 cards de resumen originales siguen funcionando
- [x] El formulario (estrategia, símbolo, fechas, balance inicial) sigue funcionando
- [x] GUI lanza sin errores JS en la consola del webview
- [x] No se rompe ninguna otra funcionalidad del bot (chart principal, tab estrategias, Data Window)
