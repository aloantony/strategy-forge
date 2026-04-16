# TASK-044: Implementación — Quick Params panel + main.py injection

- **ID**: TASK-044
- **Priority**: P1
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-042, TASK-043
- **Blocks**: —

## Files to read

- `agents/specs/TASK-042-params-schema-spec.md` — spec de Daniel: pseudocode para main.py y generator.py
- `agents/specs/TASK-043-quick-params-gui-spec.md` — spec de Grace: cambios exactos en gui_charts.py
- `main.py` — archivo a modificar
- `strategy_builder/generator.py` — archivo a modificar
- `gui_charts.py` — archivo a modificar

## Description

Implementar el panel de edición rápida de parámetros de estrategia siguiendo las specs de Daniel (TASK-042) y Grace (TASK-043). Felix traduce pseudocode a Python/JavaScript — no toma decisiones algorítmicas ni arquitectónicas.

## Acceptance criteria

- [ ] `main.py`: `_load_strategy_module()` lee `PARAMS` del módulo y lo almacena en el entry
- [ ] `main.py`: nueva función `_load_strategy_params()` merge defaults + `.params.json`
- [ ] `main.py`: `_analyze_strategy()` detecta kwarg `params` via `inspect.signature` y lo pasa cuando aplica
- [ ] `strategy_builder/generator.py`: bloque `PARAMS` emitido en el `.py` generado (derivado de `indicators[].params`)
- [ ] `gui_charts.py`: `_get_strategy_payload()` incluye `params_schema` y `params_values`
- [ ] `gui_charts.py`: botón "Params" visible para estrategias con `params_schema`
- [ ] `gui_charts.py`: `_on_strategy_params_open()` y `_on_strategy_params_save()` implementados
- [ ] `gui_charts.py`: `window.openParamsPanel()` y `window.closeParamsPanel()` implementados en JS
- [ ] Estrategia sin `PARAMS`: comportamiento idéntico al actual (cero regresiones)
- [ ] Estrategia Builder-generated: edit params → `.json` actualizado → `.py` regenerado → módulo recargado en siguiente tick
- [ ] Estrategia manual con `PARAMS`: edit params → `.params.json` guardado → `get_last_signal` recibe `params` kwarg
