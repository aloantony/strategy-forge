# TASK-045: GUI spec — Sprint GUI Polish completo

- **ID**: TASK-045
- **Priority**: P1
- **Status**: done
- **Assigned**: Grace
- **Blocked by**: —
- **Blocks**: TASK-047, TASK-048

## Files to read

- `agents/grace.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `gui_charts.py` — secciones a leer antes de especificar nada:
  - `_inject_custom_styles()` (~L1615) — bloque CSS completo; localizar punto de inserción para toast styles
  - Zona de init HTML del body (buscar `<body` y el div raíz) — localizar punto de inserción para `#tv-toast-container`
  - Selectores de botones interactivos: `.tv-strategy-toggle`, `.tv-eye`, `#tv-backtest-run`, `.tv-side-tab`, modal buttons, Quick Params modal buttons
  - JS del tab switcher (buscar el handler de click de `.tv-side-tab` o `#tv-side-tabs`) — localizar línea exacta del bloque `style.display`
  - `bot_loop()` (~L6206) — bloque `if signal != "none"` para integración de toast señal detectada
  - `_send_order()` — respuesta de orden abierta para toast trade abierto
  - `_close_position()` — respuesta de posición cerrada para toast trade cerrado
  - `self._callback_queue` — confirmar el patrón thread-safe establecido

## Description

Grace produce la spec completa del sprint GUI Polish: micro-interacciones + spinner + toast notifications. Cubre inventario de elementos interactivos, cambio quirúrgico del tab switcher (Opción B), y arquitectura del sistema de toasts. Grace NO modifica código.

## Technical context

### Entregable

Un único archivo de spec: `agents/specs/TASK-045-gui-polish-spec.md`

### Sección 1 — Micro-interacciones

- Inventario completo de botones interactivos con su selector CSS exacto
- Para cada elemento: `transition` recomendado (0.12–0.18s ease), `transform: scale(0.97)` en `:active`, `box-shadow` en hover para botones primarios
- **Tab switching Opción B** — El JS actual usa `style.display = 'none'` / `''`. Grace debe:
  1. Localizar la función JS del tab switcher (número de línea exacto en `gui_charts.py`)
  2. Especificar el cambio quirúrgico de 3 líneas:
     - Poner `display = ''` en el panel destino
     - Ejecutar `requestAnimationFrame(() => panel.classList.add('tv-tab-fade-in'))` inmediatamente después
     - CSS keyframe: `.tv-tab-fade-in { animation: tvTabFadeIn 0.18s ease forwards }`
- **Spinner en `#tv-backtest-run`**: El JS ya deshabilita el botón al ejecutar backtest. Grace debe especificar:
  - Si usar `button:disabled::after` o una clase adicional como selector para activar el spinner
  - El `@keyframes tvSpinner` + pseudo-element `::after` con `border-top` rotando
  - Confirmar que el selector no colisiona con otros botones disabled en el panel

### Sección 2 — Toast notification system

- **HTML**: `<div id="tv-toast-container">` — `position: fixed; bottom: 20px; right: 20px; z-index: 9999`
- **Cada toast**: `<div class="tv-toast tv-toast--{type}">` con borde izquierdo de 3px de acento (no fondo de color)
  - `success` → `#26a69a`, `warn` → `#e6a817`, `error` → `#ef5350`, `info` → `#4a90d9`
- **Animación**: slide-in desde la derecha (`translateX(110%)` → `translateX(0)`) + fade-out automático tras 3500ms
- **JS API**: `window.tvShowToast(message, type='info', duration=3500)` — gestiona cola, máx 4 toasts visibles
- **Python API**: `TradingBotGUI.show_toast(msg, type='info')` — thread-safe vía `self._callback_queue.put(...)`
- Grace debe confirmar que llamar `chart.run_script()` directamente desde bot-loop está prohibido y que el patrón de callback-queue es el correcto aquí

### Sección 3 — Insertion points

Grace debe especificar con número de línea exacto (o landmark inequívoco):
- Línea CSS para toast styles (dentro de `_inject_custom_styles`)
- Línea HTML para `#tv-toast-container` (en init del body)
- Línea JS para `window.tvShowToast` (en bloque de JS inyectado)
- Líneas Python para las 3 llamadas a `show_toast`:
  1. Trade abierto — en `_send_order`
  2. Trade cerrado — en `_close_position`
  3. Señal detectada — en `bot_loop` bloque `if signal != "none"`
- Línea JS del tab switcher para el cambio Opción B

## Acceptance criteria

- [ ] Spec producida en `agents/specs/TASK-045-gui-polish-spec.md`
- [ ] Inventario de botones interactivos completo con selector CSS y valores de transition/scale
- [ ] Línea exacta del tab switcher JS especificada con el cambio de 3 líneas documentado
- [ ] Selector del spinner especificado (`button:disabled::after` o clase) con justificación
- [ ] CSS del spinner (`@keyframes tvSpinner` + `::after`) definido en la spec
- [ ] HTML del `#tv-toast-container` especificado
- [ ] CSS de toasts definido (slide-in, fade-out, 4 tipos de acento)
- [ ] JS `window.tvShowToast()` especificado (cola, máx 4, auto-dismiss)
- [ ] Python `show_toast()` especificado con patrón thread-safe (callback-queue)
- [ ] Todos los insertion points documentados con número de línea o landmark inequívoco
- [ ] Threading verificado: spec confirma que `show_toast` desde bot-loop DEBE usar callback-queue
- [ ] Spec no toca colores existentes de la paleta (tema oscuro)
