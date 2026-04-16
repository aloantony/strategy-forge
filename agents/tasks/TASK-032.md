# TASK-032: Implementar comparación multi-estrategia en tab Backtest

- **ID**: TASK-032
- **Priority**: P2
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-030, TASK-029
- **Blocks**: nada

## Files to read
- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-030-backtest-comparison-gui-spec.md` — spec GUI de Grace a implementar verbatim
- `agents/specs/TASK-029-backtest-comparison-backend-spec.md` — spec backend de Daniel a implementar verbatim
- `backtesting/runtime.py` — para añadir la función de comparación definida por Daniel
- `gui_charts.py` — leer SOLO los rangos indicados en el spec de Grace

## Description

Implementar la feature de comparación multi-estrategia: (1) la función de comparación en `backtesting/runtime.py` según el spec de Daniel (TASK-029), y (2) los cambios en `gui_charts.py` según el spec de Grace (TASK-030) — formulario con multi-selección, handler Python, y tabla de resultados comparativos.

## Technical context

- Relevant files: `gui_charts.py`, `backtesting/runtime.py`
- Todos los cambios deben ser quirúrgicos en los puntos indicados por los specs.
- El modo "comparación" y el modo "single strategy" deben coexistir en el mismo tab sin conflicto.
- La función de comparación en `runtime.py` es nueva — no modifica `run_backtest` ni `BacktestEngine` existentes.
- Seguir ambos specs verbatim — sin decisiones de diseño propias.

## Acceptance criteria
- [x] `backtesting/runtime.py`: función de comparación implementada según spec TASK-029
- [x] `gui_charts.py`: formulario permite seleccionar múltiples estrategias para comparar
- [x] `gui_charts.py`: tabla de comparación muestra las métricas definidas en spec TASK-030
- [x] Modo single-strategy (TASK-031) no se rompe al añadir el modo comparación
- [x] GUI lanza sin errores JS en la consola del webview
- [x] Manejo de error parcial (fallo de una estrategia) según lo especificado por Daniel
