# TASK-030: Spec GUI — panel de comparación de estrategias en tab Backtest

- **ID**: TASK-030
- **Priority**: P2
- **Status**: todo
- **Assigned**: Grace
- **Blocked by**: TASK-029, TASK-028
- **Blocks**: TASK-032

## Files to read
- `agents/grace.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-029-backtest-comparison-backend-spec.md` — shape del request y resultado de comparación que el backend retornará
- `agents/specs/TASK-028-backtest-gui-spec.md` — cambios ya planificados al panel por TASK-028; los puntos de inserción de TASK-030 deben ser compatibles y no solapar
- `gui_charts.py` líneas 699–924 y 4425–4594 — estado actual del tab Backtest

## Description

Con el backend de comparación definido por Daniel (TASK-029), Grace debe diseñar cómo exponer la feature en el tab Backtest de la GUI. La comparación implica: (1) selección múltiple de estrategias en el formulario, (2) un botón/modo "Comparar", (3) una tabla de resultados lado a lado por estrategia.

Esta spec debe ser compatible con los cambios de TASK-028 (tabla de trades, equity curve, drawdown), que son la vista "single strategy". El panel debe alternar entre modo "single" y modo "comparison" sin romper ninguno de los dos.

## Technical context

- Relevant files: `gui_charts.py`
- Relevant sections: panel backtest completo (ver Files to read)
- La GUI actualmente tiene un `<select>` de estrategia single (`tv-backtest-strategy`). La comparación requiere multi-select o un mecanismo alternativo (checkboxes, lista con toggles). Grace decide el patrón de UI.
- El Python handler `_on_backtest_run` deberá derivar hacia la función de comparación cuando el request indica modo comparación. Grace debe especificar qué campo del request JS indica el modo, para que Felix pueda modificar `_on_backtest_run` o añadir un handler separado.
- El thread worker (`_run_backtest_worker`) deberá llamar a la función de comparación en lugar de `run_backtest` en modo comparación. Grace especifica si es un handler Python separado o una rama condicional en el existente.
- Restricción de tamaño del side panel: la tabla de comparación debe ser compacta (ancho ~280–320px). Máximo ~6 columnas de métricas clave.

## What Grace must produce

Un spec en `agents/specs/TASK-030-backtest-comparison-gui-spec.md` que incluya:

1. **Cambio al formulario**: cómo el usuario selecciona múltiples estrategias (multi-select, checkboxes, otro). IDs de elementos nuevos o modificados.
2. **Mecanismo de modo**: cómo el formulario indica a Python que es una comparación (campo en el request JSON, nuevo evento JS, o handler separado).
3. **Python side**: si se añade un método nuevo en `TradingBotGUI` o se extiende `_on_backtest_run`. Firma del método nuevo si aplica.
4. **Vista de resultados de comparación**: tabla HTML con columnas (Estrategia, Operaciones, Win rate, Max DD, Retorno %, Profit Factor). IDs de elementos.
5. **Alternancia single vs. comparison**: qué elementos se muestran/ocultan en cada modo.
6. **CSS nuevo**: clases para la tabla de comparación. Compatible con el CSS del spec TASK-028.
7. **Puntos de inserción exactos** en `gui_charts.py` para cada fragmento Python y JS (línea ± 5).

## Acceptance criteria
- [ ] Spec existe en `agents/specs/TASK-030-backtest-comparison-gui-spec.md`
- [ ] Spec define el mecanismo de multi-selección de estrategias en el formulario
- [ ] Spec define el campo del request JSON que señala modo comparación
- [ ] Spec especifica si `_on_backtest_run` se extiende o se añade handler nuevo (con firma)
- [ ] Spec define la tabla de comparación con columnas exactas
- [ ] Spec define el comportamiento de alternancia single/comparison (elementos que se ocultan)
- [ ] Spec es compatible con los puntos de inserción de TASK-028 (sin solapamiento de líneas)
- [ ] Puntos de inserción en `gui_charts.py` indicados con línea ± 5
