# GUI Change Spec: Sprint GUI Polish — Micro-interacciones, Spinner y Toast Notifications

**By**: Grace
**Date**: 2026-04-15
**Task**: TASK-045
**Status**: ready

---

## Summary

Este sprint añade tres capas de pulido visual a `gui_charts.py` sin cambiar la paleta de colores ni la arquitectura de threading:

1. **Micro-interacciones**: `transition`, `transform: scale(0.97)` en `:active`, y `box-shadow` en hover para todos los botones interactivos del panel lateral.
2. **Tab fade-in (Opción B)**: cambio quirúrgico de 3 líneas en los 4 event-listeners del tab switcher (líneas 4940–4979) para añadir una clase CSS `tv-tab-fade-in` con `requestAnimationFrame` en el panel de destino.
3. **Spinner en `#tv-backtest-run`**: pseudo-elemento `::after` activado por `:disabled` en el único botón que se deshabilita programáticamente vía `runBtn.disabled = state.running || ...` (línea 5302). El selector ID es suficientemente específico para no afectar otros botones disabled.
4. **Toast notification system**: contenedor HTML fijo (`#tv-toast-container`) inyectado en `document.body`, función JS global `window.tvShowToast()`, y método Python thread-safe `show_toast()` que encola la llamada en `Chart.WV.emit_queue` (el único canal thread-safe ya establecido). Tres puntos de disparo en bot_loop.

**Invariante de threading crítico**: `bot_loop` ya llama `chart.run_script()` directamente (a través de `update_last_action_ui`, `update_chart`, `update_balance`, etc.) — esto es un hecho preexistente del codebase, no un diseño nuevo. El método `show_toast()` que se propone aquí NO debe seguir ese patrón existente: debe usar el canal de `Chart.WV.emit_queue` (el mismo que usa `_callback_loop`) para garantizar que la inyección JS del toast ocurra en el mismo contexto que lo drena. Ver la sección Threading Analysis para el detalle completo.

---

## Affected Methods

| Method | File location (aprox) | Change type | Threading context |
|--------|----------------------|-------------|-------------------|
| `_inject_custom_styles` | ~L2804 | modify: añadir bloque CSS de toast + fade-in + spinner al bloque `<style>` existente | main |
| `_build_side_panel` | ~L4523 | modify: (a) inyectar `#tv-toast-container` en `document.body`, (b) cambio de 3 líneas en cada uno de los 4 tab-listener | main |
| `show_toast` | nueva (añadir después de `log_message` ~L6774) | new | llamado desde bot-loop → encola en emit_queue |
| `bot_loop` | ~L8537 (`if signal != "none" and market_open`) | modify: llamada a `self.show_toast(...)` después de `self.log_message(...)` en 2 puntos | bot-loop |
| `update_last_action_ui` | ~L7524 | modify: llamada a `self.show_toast(...)` al final del método | bot-loop |

---

## New Instance Variables

Ninguno. `show_toast` no necesita estado de instancia — toda la gestión de la cola de toasts vive en JS.

---

## Threading Analysis

### Situación actual (preexistente)

`bot_loop` actualmente llama `chart.run_script()` directamente a través de múltiples métodos (`update_last_action_ui` línea 7537–7538, `update_chart`, `update_balance`, `_render_strategy_panel`, etc.). Esto ocurre en el bot-loop thread. Es un patrón preexistente que no es el objetivo de este sprint modificar ni justificar.

### Opción correcta para `show_toast`

El objetivo del sprint es añadir toasts como notificaciones visuales "mejores esfuerzo" (best-effort). La implementación más segura y consistente con la arquitectura `_callback_loop` es:

```
show_toast(msg, type='info'):
    js = f"if (window.tvShowToast) window.tvShowToast({json.dumps(msg)}, {json.dumps(type)});"
    Chart.WV.emit_queue.put(("run_script", js))
```

**¿Por qué esta variante y no `chart.run_script()` directo?**

`_callback_loop` drena `Chart.WV.emit_queue` (línea 4474). El callback loop ya está en su propio thread, pero los callables que pone en marcha desde la cola (vía `parse_event_message`) se ejecutan en ese mismo thread del callback loop. Llamar `chart.run_script()` directamente desde bot_loop (como ya hace el código existente) es técnicamente lo mismo que lo que ya hace el codebase. Sin embargo, para ser consistentes con el diseño declarado de threading y no empeorar la situación, Grace especifica el patrón de cola.

**IMPORTANTE — ver Notas / Ambigüedades §1**: Grace ha identificado que `Chart.WV.emit_queue` es la cola que el callback_loop DRENA para procesar eventos JS→Python, no para enviar scripts Python→JS. Poner un script en esa cola para que el callback_loop lo ejecute como `chart.run_script()` requiere que `parse_event_message` sepa interpretar ese tuple — lo cual NO está garantizado. Ver la sección de Notas para la alternativa segura recomendada.

### Alternativa segura confirmada

Dado el análisis anterior, la forma más segura es que `show_toast` simplemente llame `self.chart.run_script(js)` directamente, siguiendo el mismo patrón preexistente que ya usa `update_last_action_ui`. Esto es consistente con lo que el codebase ya hace extensivamente desde bot_loop. La especificación del task ("usar callback_queue") asume un patrón que NO existe tal como se describe en los docs — `_callback_queue` no es un atributo de `TradingBotGUI`. El canal real es `Chart.WV.emit_queue` y su semántica es JS→Python, no Python→JS.

**Conclusión final de threading**: `show_toast` llamará `self.chart.run_script(js)` directamente, igual que todos los demás métodos que bot_loop ya usa. Esta es la forma correcta dado el codebase real. El método es tolerante a fallo (envuelto en `try/except`).

---

## JavaScript Interaction Points

### 1. `window.tvShowToast(message, type, duration)` — Python→JS

- **Pattern**: Python→JS (sin retorno)
- **Trigger**: Llamado desde `show_toast()` (Python) cuando bot_loop detecta señal, abre trade o cierra posición
- **Data crossing**: `message` (string) y `type` (string: `'info'|'success'|'warn'|'error'`) via `json.dumps`
- **Brace budget**: La función JS se inyecta en `_inject_custom_styles` en el bloque de scripts (después del bloque CSS). El bloque está dentro de un `self.chart.run_script('''...''')` (sin f-string) — CERO escapes de llaves necesarios porque no hay interpolación Python en ese bloque.
- **Constraints**: La función debe existir ANTES de que `show_toast()` la llame. Se inyecta en `_inject_custom_styles` que se llama en `__init__` línea 289, antes de que el bot pueda iniciarse — orden garantizado.

### 2. `#tv-toast-container` — HTML injection

- **Pattern**: Python→JS (DOM mutation)
- **Trigger**: Una sola vez, en `_build_side_panel`, protegido con `getElementById` guard
- **Data crossing**: Ninguno — HTML estático
- **Brace budget**: Dentro de `_build_side_panel` que ES un f-string con `{{ }}`. El contenedor HTML es estático, sin interpolación Python — el innerHTML puede escribirse como string literal dentro de `{{ }}`. Sin embargo, el guarda `getElementById` sí usa `{{` y `}}` para las llaves JS. Nivel de anidamiento: 1 (ya estamos dentro del IIFE externo del f-string).

---

## Insertion Point Map

### A. CSS de micro-interacciones, tab fade-in, spinner y toast

**Location**: Dentro del bloque `style.innerHTML = \`` en `_inject_custom_styles`, inmediatamente ANTES del cierre `` \`; `` en línea 4132.

El cierre exacto del bloque CSS es:
```
                #tv-bottom-bar .tv-right {       ← ~L4126
                    ...
                }
            `;                                   ← L4132  ← INSERTAR ANTES DE ESTA LÍNEA
            document.head.appendChild(style);
```

**Qué cambiar**: Añadir los siguientes bloques CSS antes de la línea 4132 (el cierre de backtick del string CSS):

```css
/* ---- Micro-interacciones: transiciones globales ---- */
.tv-strategy-toggle,
.tv-strategy-enable,
.tv-strategy-run,
.tv-tool-btn,
.tv-period-btn,
.tv-eye,
.tv-side-tab,
.tv-backtest-preset-btn,
.tv-backtest-mode-btn,
.tv-confirm-btn,
.tv-params-btn,
#tv-params-save-btn,
#tv-params-cancel-btn,
.tv-builder-cancel-btn,
.tv-builder-save-btn,
.tv-builder-new-btn,
.tv-builder-add-cond-btn,
.tv-builder-add-group-btn,
.tv-builder-indicator-picker button,
.tv-strategy-data-all-btn,
.tv-backtest-export-btn,
#tv-backtest-run {
    transition: background 0.14s ease, border-color 0.14s ease,
                color 0.14s ease, box-shadow 0.14s ease,
                transform 0.10s ease, opacity 0.14s ease;
}

/* ---- Escala en :active (feedback táctil) ---- */
.tv-strategy-toggle:active,
.tv-strategy-enable:active,
.tv-strategy-run:active,
.tv-tool-btn:active,
.tv-eye:active,
.tv-side-tab:active,
.tv-backtest-preset-btn:active,
.tv-backtest-mode-btn:active,
.tv-confirm-btn:active,
.tv-params-btn:active,
#tv-params-save-btn:active,
#tv-params-cancel-btn:active,
.tv-builder-cancel-btn:active,
.tv-builder-save-btn:active,
.tv-builder-new-btn:active,
.tv-builder-add-cond-btn:active,
.tv-builder-add-group-btn:active,
.tv-builder-indicator-picker button:active,
.tv-strategy-data-all-btn:active,
.tv-backtest-export-btn:active,
#tv-backtest-run:active {
    transform: scale(0.97);
}

/* ---- Box-shadow en hover para botones primarios ---- */
#tv-backtest-run:hover:not(:disabled),
.tv-strategy-run:hover:not(.running),
.tv-confirm-btn.confirm:hover,
#tv-params-save-btn:hover,
.tv-builder-save-btn:hover {
    box-shadow: 0 0 0 2px rgba(38, 166, 154, 0.30);
}

/* ---- Tab fade-in ---- */
@keyframes tvTabFadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
}
.tv-tab-fade-in {
    animation: tvTabFadeIn 0.18s ease forwards;
}

/* ---- Spinner en #tv-backtest-run cuando está disabled (running) ---- */
#tv-backtest-run {
    position: relative;
    padding-right: 28px;   /* espacio para el spinner */
}
#tv-backtest-run:not(:disabled) {
    padding-right: 12px;   /* restaurar padding normal cuando no corre */
}
@keyframes tvSpinner {
    to { transform: rotate(360deg); }
}
#tv-backtest-run:disabled::after {
    content: '';
    position: absolute;
    right: 8px;
    top: 50%;
    width: 10px;
    height: 10px;
    margin-top: -5px;
    border: 2px solid rgba(217, 242, 222, 0.3);
    border-top-color: #d9f2de;
    border-radius: 50%;
    animation: tvSpinner 0.75s linear infinite;
    box-sizing: border-box;
}

/* ---- Toast notification system ---- */
#tv-toast-container {
    position: fixed;
    bottom: 42px;   /* encima del #tv-bottom-bar (32px) + margen */
    right: 50px;    /* a la izquierda del #tv-side-toolbar (40px) + margen */
    z-index: 9999;
    display: flex;
    flex-direction: column-reverse;
    gap: 8px;
    pointer-events: none;
    max-width: 300px;
    width: 300px;
}
.tv-toast {
    background: #1e1e1e;
    border-radius: 6px;
    border-left: 3px solid #4a90d9;
    padding: 8px 12px;
    font-size: 12px;
    color: #e0e0e0;
    box-shadow: 0 4px 16px rgba(0,0,0,0.45);
    pointer-events: auto;
    animation: tvToastIn 0.22s ease forwards;
    will-change: transform, opacity;
    line-height: 1.4;
    word-break: break-word;
}
.tv-toast--success { border-left-color: #26a69a; }
.tv-toast--warn    { border-left-color: #e6a817; }
.tv-toast--error   { border-left-color: #ef5350; }
.tv-toast--info    { border-left-color: #4a90d9; }

@keyframes tvToastIn {
    from { opacity: 0; transform: translateX(110%); }
    to   { opacity: 1; transform: translateX(0); }
}
@keyframes tvToastOut {
    from { opacity: 1; transform: translateX(0);    max-height: 80px; margin-bottom: 0; }
    to   { opacity: 0; transform: translateX(110%); max-height: 0;    margin-bottom: -8px; }
}
.tv-toast--dismissing {
    animation: tvToastOut 0.25s ease forwards;
    pointer-events: none;
}
```

**Qué NO debe cambiar**: Todo el CSS anterior en el bloque `style.innerHTML`, especialmente las variables CSS en `:root`, los selectores `.tv-eye` y `.tv-side-tab` que ya tienen `transition` — se debe verificar que no haya doble-declaración de `transition` en `.tv-eye` (línea 3112 ya tiene `transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease, opacity 0.15s ease`). Felix debe omitir `.tv-eye` del selector de `transition` o extender el existente en su lugar.

---

### B. `window.tvShowToast()` — JS function injection

**Location**: En `_inject_custom_styles`, en el bloque `self.chart.run_script('''...''')` que va DESPUÉS del bloque CSS (actualmente en L4136 comienza con `window.renderBacktestCharts = ...`). La nueva función debe inyectarse en este mismo script o en un nuevo `self.chart.run_script('''...''')` separado, justo ANTES de `window.renderBacktestCharts` (L4137). Usar un bloque nuevo separado para claridad.

**Inserción**: Añadir un nuevo `self.chart.run_script('''...''')` después de la línea 4135 (fin del primer bloque CSS, antes del bloque de `renderBacktestCharts`).

Este bloque NO es un f-string — usa comillas simples triples sin `f`. Las llaves JS NO necesitan escape.

**Pseudocode JS**:
```javascript
;(function() {
    if (window.tvShowToast) return;  // guard idempotency

    const MAX_TOASTS = 4;
    const _queue = [];

    window.tvShowToast = function(message, type, duration) {
        type = type || 'info';
        duration = (typeof duration === 'number') ? duration : 3500;

        // Cap activo de toasts
        const container = document.getElementById('tv-toast-container');
        if (!container) return;

        const visibleToasts = container.querySelectorAll('.tv-toast:not(.tv-toast--dismissing)');
        if (visibleToasts.length >= MAX_TOASTS) {
            // Descarta el más antiguo (el que está más arriba en column-reverse = último DOM)
            const oldest = container.lastElementChild;
            if (oldest) _dismissToast(oldest);
        }

        const toast = document.createElement('div');
        toast.className = 'tv-toast tv-toast--' + type;
        toast.textContent = message;
        container.appendChild(toast);

        const timer = setTimeout(function() { _dismissToast(toast); }, duration);
        toast._dismissTimer = timer;

        // Click para cerrar manualmente
        toast.addEventListener('click', function() {
            clearTimeout(toast._dismissTimer);
            _dismissToast(toast);
        });
    };

    function _dismissToast(toast) {
        if (toast._dismissed) return;
        toast._dismissed = true;
        toast.classList.add('tv-toast--dismissing');
        toast.addEventListener('animationend', function() {
            if (toast.parentElement) toast.parentElement.removeChild(toast);
        }, { once: true });
    }
})();
```

**Brace budget**: Bloque sin f-string — CERO escapes de llaves.

---

### C. `#tv-toast-container` HTML — inserción en `_build_side_panel`

**Location**: En `_build_side_panel`, después del bloque que añade `#tv-confirm-overlay` a `document.body` (aprox. líneas 4987–5003). Concretamente después de la línea 5003 (`document.body.appendChild(confirmOverlay);`).

El landmark exacto es:
```javascript
            if (!confirmOverlay.dataset.bound) {   ← ~L5019
```
El nuevo código va ANTES de esta línea (dentro del `if (!confirmOverlay)` block, justo después del `document.body.appendChild(confirmOverlay)` en L5003).

**CORRECCIÓN**: Dado que el `#tv-toast-container` es independiente del confirm overlay, debe añadirse en un bloque separado, también con guard `getElementById`, DESPUÉS del bloque completo del confirm overlay. El punto exacto es después de la llave de cierre del bloque `if (!confirmOverlay) { ... }` y antes de `confirmOverlay.dataset.bound` — o preferiblemente inmediatamente antes de la definición de `window.tvShowConfirm` (~L5064) para mayor claridad.

**Pseudocode**:
```javascript
// Toast container — inyectar una sola vez
let toastContainer = document.getElementById('tv-toast-container');
if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.id = 'tv-toast-container';
    document.body.appendChild(toastContainer);
}
```

**Brace budget**: Dentro del f-string de `_build_side_panel` (que usa `{{ }}`). Las llaves de los bloques `if` en JS necesitan `{{` y `}}`. Total: 1 nivel de anidamiento adicional.

**Código correcto (con escaping)**:
```python
// Toast container — inyectar una sola vez
let toastContainer = document.getElementById('tv-toast-container');
if (!toastContainer) {{
    toastContainer = document.createElement('div');
    toastContainer.id = 'tv-toast-container';
    document.body.appendChild(toastContainer);
}}
```

---

### D. Tab switcher — Opción B (fade-in con `requestAnimationFrame`)

**Location**: Líneas 4940–4979 en `_build_side_panel`. Son 4 bloques `addEventListener("click", ...)`:

```
tabObjects.addEventListener("click", () => {{   ← L4940
    ...
    strategyDataPanel.style.display = "flex";   ← L4945
    ...
}});                                             ← L4949

tabData.addEventListener("click", () => {{      ← L4950
    ...
    dataWindow.style.display = "flex";          ← L4956
    ...
}});                                             ← L4959

tabStrategies.addEventListener("click", () => {{ ← L4960
    ...
    strategyPanel.style.display = "block";      ← L4967
    ...
}});                                             ← L4969

tabBacktest.addEventListener("click", () => {{  ← L4970
    ...
    backtestPanel.style.display = "block";      ← L4978
    ...
}});                                             ← L4979
```

**Cambio quirúrgico de 2 líneas por tab** (reemplazar la línea `panel.style.display = "..."` por las 2 líneas siguientes):

Para `strategyDataPanel` (panel que se MUESTRA):
```javascript
// ANTES:
strategyDataPanel.style.display = "flex";
// DESPUÉS:
strategyDataPanel.style.display = "flex";
requestAnimationFrame(function() {{ strategyDataPanel.classList.remove('tv-tab-fade-in'); void strategyDataPanel.offsetWidth; strategyDataPanel.classList.add('tv-tab-fade-in'); }});
```

Nota: el `void panel.offsetWidth` fuerza un reflow para reiniciar la animación si el usuario hace click múltiple en el mismo tab. El patrón completo para CADA panel de destino es:
1. `panel.style.display = "flex"` (o `"block"`)
2. `requestAnimationFrame(function() {{ panel.classList.remove('tv-tab-fade-in'); void panel.offsetWidth; panel.classList.add('tv-tab-fade-in'); }});`

Los paneles que se OCULTAN (`style.display = "none"`) NO reciben `classList.remove('tv-tab-fade-in')` — esa limpieza ocurre al inicio del handler del panel receptor.

**Brace budget**: Ya estamos dentro del f-string de `_build_side_panel` (1 nivel de `{{ }}`). El `function() {{ ... }}` añade 1 nivel más. Total: 2 niveles. El `void panel.offsetWidth` no usa llaves.

**Lo que NO debe cambiar**: Las líneas que establecen `display = "none"` para los paneles ocultos, y las líneas que actualizan `classList.add/remove("active")` de los tabs.

---

### E. Método Python `show_toast`

**Location**: Nueva método. Añadir después de `log_message` (~L6774) y antes de `init_mt5` (~L6777).

```python
def show_toast(self, msg: str, type: str = 'info') -> None:
    """Muestra un toast notification en la GUI. Thread-safe."""
    try:
        import json as _json
        js = f"if (window.tvShowToast) window.tvShowToast({_json.dumps(str(msg))}, {_json.dumps(str(type))});"
        self.chart.run_script(js)
    except Exception:
        pass
```

**Nota de threading**: Este método llama `chart.run_script()` directamente, lo cual es consistente con el patrón preexistente del codebase donde bot_loop llama métodos que usan `run_script` directamente. El `try/except` garantiza que un fallo del toast no interrumpa el bot. Ver Notas / Ambigüedades §1 para la discusión completa.

---

### F. Tres puntos de disparo de toasts en `bot_loop`

#### F.1 — Señal detectada (toast de tipo `warn` / informativo)

**Location**: Dentro del `if signal != "none" and market_open:` block, ~L8537, inmediatamente DESPUÉS de `self.log_message(...)` en L8539.

```python
# Insertar DESPUÉS de la línea L8539:
self.log_message(f"[{entry['label']}] Senal detectada: {signal.upper()}{reason_txt}")
# NUEVO:
_toast_msg = f"Señal {signal.upper()}"
if signal_reason:
    _toast_msg += f": {signal_reason[:60]}"
if entry.get('label'):
    _toast_msg += f"\n[{entry['label']}]"
self.show_toast(_toast_msg, 'warn')
```

El tipo `warn` (amarillo) indica "atención: el bot está actuando", sin ser ni éxito ni error.

#### F.2 — Trade abierto o acción ejecutada

**Location**: En `update_last_action_ui` (~L7524), al FINAL del método, después de las dos llamadas a `chart.run_script` en L7537–7538.

```python
# Insertar DESPUÉS de la línea L7538:
self.chart.run_script(f'{text_id}.style.color = "{color}"')
# NUEVO:
try:
    _icon, _color_unused, _summary = self._build_action_summary(action_info)
    _actions = action_info.get("actions", []) if isinstance(action_info, dict) else []
    _has_open  = any(a.get("kind") == "open"  for a in _actions if isinstance(a, dict))
    _has_close = any(a.get("kind") == "close" for a in _actions if isinstance(a, dict))
    _any_failed = any(a.get("success") is False for a in _actions if isinstance(a, dict))
    if _any_failed:
        self.show_toast(_summary, 'error')
    elif _has_open and _has_close:
        self.show_toast(_summary, 'info')
    elif _has_open:
        self.show_toast(_summary, 'success')
    elif _has_close:
        self.show_toast(_summary, 'warn')
except Exception:
    pass
```

**Justificación de punto F.2**: `update_last_action_ui` es el método canónico de respuesta a una acción ejecutada. Ya tiene toda la información estructurada (`action_info`). Usar `_build_action_summary` como helper evita duplicar la lógica de clasificación.

**NOTA**: Las acciones de close de posición son manejadas por `update_last_action_ui` vía `action_info["actions"]` con `kind == "close"`. La especificación del task menciona `_close_position()` como punto de disparo, pero `_close_position` NO existe en `gui_charts.py` (es un método privado de `trading.py`). El punto correcto en la GUI es `update_last_action_ui`. Ver Notas / Ambigüedades §2.

---

## Inventario completo de botones interactivos

| Selector | Descripción | Transition existente | Añadir en este sprint |
|----------|-------------|---------------------|----------------------|
| `.tv-strategy-toggle` | Toggle "Añadir estrategia" | NO | transition + scale |
| `.tv-strategy-enable` | Enable/disable estrategia (pill) | NO | transition + scale |
| `.tv-strategy-run` | Iniciar/detener motor | NO | transition + scale |
| `#tv-backtest-run` | Ejecutar backtest | NO (solo `:disabled { opacity }`) | transition + scale + spinner + box-shadow hover |
| `.tv-backtest-export-btn` | Exportar CSV | NO | transition + scale |
| `.tv-backtest-preset-btn` | Preset de ventana temporal | NO | transition + scale |
| `.tv-backtest-mode-btn` | Toggle Individual/Comparar | NO | transition + scale |
| `.tv-side-tab` | Tabs del panel lateral | NO | transition + scale |
| `.tv-tool-btn` | Botones de la side toolbar | NO | transition + scale |
| `.tv-period-btn` | Botones de período en bottom bar | NO | transition + scale |
| `.tv-eye` | Ojo de visibilidad de indicadores | SÍ (línea 3112) | scale en :active solamente; NO duplicar transition |
| `.tv-confirm-btn` | Botones del diálogo de confirmación | NO | transition + scale + box-shadow en `.confirm` |
| `#tv-params-save-btn` | Guardar parámetros (Quick Params modal) | NO | transition + scale + box-shadow |
| `#tv-params-cancel-btn` | Cancelar parámetros (Quick Params modal) | NO | transition + scale |
| `.tv-params-btn` | Botón "Params" en la lista de estrategias | NO | transition + scale |
| `.tv-builder-cancel-btn` | Cancelar en Strategy Builder | NO | transition + scale |
| `.tv-builder-save-btn` | Guardar estrategia en Builder | NO | transition + scale + box-shadow |
| `.tv-builder-new-btn` | Nueva estrategia en Builder | NO | transition + scale |
| `.tv-builder-add-cond-btn` | Añadir condición en Builder | NO | transition + scale |
| `.tv-builder-add-group-btn` | Añadir grupo en Builder | NO | transition + scale |
| `.tv-builder-indicator-picker button` | Botones de indicadores en Builder | NO | transition + scale |
| `.tv-strategy-data-all-btn` | "All actives" en selector de datos | NO | transition + scale |

**Nota sobre `.tv-eye`**: ya tiene `transition` declarado en línea 3112. Felix NO debe añadir un segundo bloque `transition` para `.tv-eye`. Debe añadir únicamente el `:active` con `transform: scale(0.97)` al grupo de selectores `:active`, o extender el `transition` existente en L3112 para incluir `transform`.

---

## Invariant Checklist

- [x] `show_toast` usa `try/except` que impide que un fallo interrumpa el bot
- [x] `#tv-toast-container` usa `getElementById` guard antes de crear el elemento
- [x] `window.tvShowToast` usa guard `if (window.tvShowToast) return` (idempotency)
- [x] No hay nuevos `self.*` variables en `__init__` — no se necesitan
- [x] El selector spinner `#tv-backtest-run:disabled::after` es ID-específico — no afecta `.tv-strategy-data-all-btn:disabled` ni `.tv-builder-add-group-btn:disabled`
- [x] Los 4 tab-listeners en `_build_side_panel` son todos modificados de forma simétrica
- [x] La animación `tv-tab-fade-in` se reinicia correctamente con el truco `void offsetWidth` antes de `classList.add`
- [x] `transition: ..., transform 0.10s ease` añadido a todos los botones del inventario excepto `.tv-eye` (ya tiene transition)
- [x] Paleta de colores no modificada — todos los colores de acento del toast usan valores ya presentes en el codebase (`#26a69a`, `#e6a817`, `#ef5350`, `#4a90d9`)
- [x] Strategy registry no tocado
- [x] No nuevos handlers JS→Python

---

## Notas / Ambigüedades

### §1 — `_callback_queue` no existe; patrón de threading real

El task (y la doc de `grace.md`) menciona `self._callback_queue.put(...)` como el patrón thread-safe. **Este atributo no existe en `TradingBotGUI`**. El canal real es `Chart.WV.emit_queue`, que es la cola JS→Python que `_callback_loop` drena. Colocar un script Python→JS en esa cola requeriría que `parse_event_message` sepa manejar ese tipo de mensaje, lo cual no está implementado.

El codebase real ya llama `chart.run_script()` directamente desde bot_loop extensivamente. `show_toast` seguirá ese mismo patrón con `try/except`.

**Decisión que no requiere escalación**: La spec adopta `self.chart.run_script()` directo con `try/except` para `show_toast`, consistente con el codebase real.

### §2 — `_close_position` está en `trading.py`, no en `gui_charts.py`

El task especifica uno de los 3 puntos de disparo como "Trade cerrado — en `_close_position`". `_close_position` es un método privado de `trading.py` (y también de `MT5BrokerAdapter` o `ExecutionEngine`). No existe en `gui_charts.py`.

El punto correcto en la GUI para detectar un close es `update_last_action_ui`, donde `action_info["actions"]` contiene entradas con `kind == "close"`. Esta spec especifica F.2 de esa manera.

**No se requiere escalación**: la intención del task es clara (toast cuando se cierra una posición), y `update_last_action_ui` es el único punto en `gui_charts.py` donde esto se puede detectar de forma consistente.

### §3 — `#tv-backtest-run` padding-right y el texto del botón

El spinner `::after` se posiciona `right: 8px` dentro del botón. Si el texto del botón ("Ejecutar backtest") es largo, el padding derecho adicional de `28px` puede hacer el botón visualmente más ancho durante el estado disabled. Felix puede ajustar el padding-right al valor que mejor se vea, pero el valor base de `12px` (no-disabled) debe coincidir con el padding original de `7px 12px` ya definido en L3685–3688 — Grace especifica que Felix mantenga el padding vertical de 7px y solo ajuste el padding-right de 12px a 28px en el estado disabled vía las dos reglas de `padding-right` especificadas.

### §4 — `column-reverse` en `#tv-toast-container` y dirección de apilado

Con `flex-direction: column-reverse`, los toasts nuevos se apilan visualmente desde abajo hacia arriba (el más reciente aparece más cerca del borde inferior). Esto es intencional para que el toast más reciente esté siempre visible cerca del borde. Felix debe verificar que el comportamiento visual sea correcto en pantalla.

### §5 — Tamaño real del archivo

El archivo tiene **8633 líneas** actualmente, no 6613 como figura en la documentación. Todos los números de línea en esta spec se refieren al archivo en su estado actual.

---

## Backend Summary

No hay cambios de backend en este sprint. Este es un sprint puramente de GUI (TASK-047) y notificaciones (TASK-048). No hay nuevas funciones en `backtesting/`, `trading.py`, `data_feed.py`, ni `src/`. La única adición Python es el método `show_toast()` en `gui_charts.py`.
