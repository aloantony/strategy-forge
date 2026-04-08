# TASK-022: GUI spec — reflejo de piramidado y riesgo en la interfaz

- **ID**: TASK-022
- **Priority**: P1
- **Status**: done
- **Assigned**: Grace
- **Blocked by**: TASK-020, TASK-021
- **Blocks**: TASK-026

## Files to read
- `agents/grace.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-020-pyramiding-spec.md` — spec de piramidado de Daniel
- `agents/specs/TASK-021-dynamic-sizing-risk-spec.md` — spec de sizing y riesgo de Daniel
- `gui_charts.py` — secciones: `update_last_action_ui` (~5314), `_ensure_action_tooltip` (~5488), `setup_side_panel` (~2957), `_build_side_panel` (~2978), `on_side_panel_event` (~4209)

## Description
Grace especifica los cambios necesarios en `gui_charts.py` para reflejar el piramidado y el riesgo. Dos componentes: (1) evaluar si el sistema de marcadores existente soporta múltiples entradas por ciclo, y (2) un **widget visual de riesgo en la pestaña de Estrategias** que muestre el riesgo agregado actual vs. el límite. El widget es obligatorio.

## Technical context
- Cada entrada piramiada generará un resultado de `apply_signal` con `actions` — el flujo actual renderiza una acción por ciclo; con piramidado puede haber múltiples acciones por ciclo
- **Widget de riesgo (decisión cerrada)**: formato mínimo "Riesgo: X.X% / 3.0%", ubicado en la pestaña Estrategias
- Base del cálculo: `account_info().balance` (no equity flotante)
- `gui_charts.py` es el archivo de mayor riesgo (~6374 líneas) — cambios mínimos y justificados
- Output: `agents/specs/TASK-022-pyramiding-gui-spec.md`

## Acceptance criteria
- [ ] Decisión documentada: ¿se necesitan cambios para soportar múltiples entradas por ciclo? Si sí, puntos exactos
- [ ] Si se necesitan cambios en marcadores: punto de inserción exacto, descripción del delta, threading zone
- [ ] Widget de riesgo especificado: punto de inserción en pestaña Estrategias, HTML/JS del elemento, mecanismo de actualización, función Python que suministra el dato
- [ ] Si no se necesitan cambios en marcadores: justificación de por qué el flujo actual es suficiente
- [ ] `agents/specs/TASK-022-pyramiding-gui-spec.md` creado y autosuficiente para que Felix implemente TASK-026
