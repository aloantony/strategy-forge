# TASK-048: Sistema de toast notifications

- **ID**: TASK-048
- **Priority**: P2
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-045
- **Blocks**: —

## Files to read

- `agents/felix.md` — tu definición de rol y workflow
- `agents/specs/TASK-045-gui-polish-spec.md` — spec de Grace: HTML del container, CSS (slide-in, fade-out, 4 tipos), JS `tvShowToast`, Python `show_toast`, los 3 insertion points en Python (líneas exactas)
- `gui_charts.py` — leer las secciones en los insertion points exactos que Grace especifique antes de editar

## Description

Implementar el sistema completo de toast notifications no bloqueantes. Incluye: HTML del container, CSS de animaciones, función JS de cola, método Python thread-safe, e integración en los 3 puntos del bot: trade abierto, trade cerrado, señal detectada. Felix implementa siguiendo la spec de Grace — no toma decisiones de arquitectura.

## Technical context

- **HTML**: inyectar `<div id="tv-toast-container">` en el init del body en la línea que Grace especifique
- **CSS**: inyectar estilos de toast dentro de `_inject_custom_styles()` en la línea que Grace especifique — slide-in desde derecha, fade-out a los 3500ms, borde de acento de 3px sin fondo de color, 4 tipos (`success`, `warn`, `error`, `info`)
- **JS**: inyectar `window.tvShowToast(message, type, duration)` — cola de máx 4 toasts, auto-dismiss, sin duplicados
- **Python `show_toast(msg, type='info')`**: método en `TradingBotGUI` — llama `self.chart.run_script(...)` directamente dentro de `try/except Exception`. Este es el patrón establecido en el codebase (`update_balance`, `update_chart`, etc.). `self._callback_queue` no existe.
- **3 puntos de integración** (líneas exactas en spec de Grace):
  1. `_send_order()` — trade abierto → `show_toast(f"Trade abierto: {symbol}", "success")`
  2. `_close_position()` — trade cerrado → `show_toast(f"Posición cerrada: {symbol}", "info")`
  3. `bot_loop()` bloque `if signal != "none"` — señal detectada → `show_toast(f"Señal: {signal}", "info")`

## Acceptance criteria

- [ ] `#tv-toast-container` inyectado en HTML del body
- [ ] CSS de toasts inyectado en `_inject_custom_styles()` — slide-in y fade-out funcionando
- [ ] Los 4 tipos de toast tienen borde de acento correcto (sin cambiar colores de la paleta existente)
- [ ] `window.tvShowToast()` implementado — máx 4 toasts simultáneos, auto-dismiss a 3500ms
- [ ] `TradingBotGUI.show_toast()` implementado con `chart.run_script()` directo dentro de `try/except Exception`
- [ ] Toast aparece al detectar señal en bot-loop
- [ ] Toast aparece al abrir un trade (`_send_order`)
- [ ] Toast aparece al cerrar una posición (`_close_position`)
- [ ] Toasts desaparecen solos tras ~3.5s sin interacción del usuario
- [ ] Sin regresiones en threading: bot-loop, quote-loop y callback-loop se comportan igual
- [ ] Sin regresiones visuales en chart principal, sub-charts TCI y equity
