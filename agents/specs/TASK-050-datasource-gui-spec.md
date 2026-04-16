# GUI Change Spec: Selector de fuente de datos en formulario de backtest

**By**: Grace
**Date**: 2026-04-15
**Task**: TASK-050
**Status**: ready

---

## Backend Summary

Daniel (TASK-049) defines `src/data/factory.py` with two public functions Felix must know:

1. `build_data_source(source_name: str, symbol_mt5: str) -> IHistoricalDataSource`
   - `source_name`: `"mt5"` | `"dukascopy"`
   - `symbol_mt5`: símbolo en formato MT5 (e.g. `"#Germany40"`, `"EURUSD"`)
   - Lanza `ValueError` con mensaje legible si: símbolo sin entrada en `symbols.json`, sin `providers.dukascopy`, o `dukascopy-python` no instalado.
   - Retorna instancia concreta, lista para pasar a `run_backtest` / `run_backtest_comparison`.

2. `resolve_symbol_for_request(source_name: str, symbol_mt5: str) -> str`
   - MT5 → devuelve `symbol_mt5` sin cambios.
   - Dukascopy → devuelve el símbolo canónico (`"GER40"`, `"EURUSD"`).
   - El resultado es lo que va en `request["symbol"]`.

`run_backtest(request, data_source=None)` y `run_backtest_comparison(request, data_source=None)` ya tienen la firma correcta. `backtesting/runtime.py` no cambia.

Alex (TASK-051) implementa el código Python en `gui_charts.py`. Felix (TASK-052) implementa el HTML/JS en `gui_charts.py` siguiendo esta spec.

---

## Summary

Este cambio añade un `<select>` de fuente de datos ("MT5" / "Dukascopy") al formulario de backtest existente, entre el campo "Símbolo" y el campo "Timeframe" (readonly). El selector se renderiza en HTML estático dentro del template del panel (`backtestPanel.innerHTML`, línea ~4865), se restaura su valor en `renderBacktestPanel` (JavaScript, línea ~5384), y su valor se incluye en el payload JSON que el botón "Ejecutar backtest" y el botón "Comparar estrategias" envían a Python. En Python, los handlers `_on_backtest_run` y `_on_backtest_compare` leen el nuevo campo, llaman a `build_data_source()` y `resolve_symbol_for_request()` antes de lanzar el worker thread, y muestran el error inline si el factory lanza `ValueError`. No se introduce ningún JS→Python handler nuevo; el flujo existente de `backtest_run` / `backtest_compare` no cambia.

---

## Affected Methods

| Método | Línea aprox. | Tipo de cambio | Contexto de threading |
|--------|-------------|----------------|----------------------|
| `_build_side_panel` — HTML template | ~4880–4883 | modify (insert HTML) | main thread (setup) |
| `renderBacktestPanel` (JS dentro de `_build_side_panel`) | ~5397–5511 | modify (DOM get + restore + send) | callback thread (lectura de DOM) |
| compare button onclick (JS dentro de `_build_side_panel`) | ~5721–5731 | modify (add field to request) | callback thread (lectura de DOM) |
| `_get_backtest_form_state` | ~753–786 | modify (add `data_source` field) | callback thread (via `_on_backtest_run`) |
| `_on_backtest_run` | ~873–962 | modify (read + validate + factory + resolve) | callback thread |
| `_run_backtest_worker` | ~859–871 | modify (signature + pass data_source) | worker thread (daemon) |
| `_on_backtest_compare` | ~964–1057 | modify (read + validate + factory + resolve) | callback thread |
| `_run_backtest_comparison_worker` | ~1059–1072 | modify (signature + pass data_source) | worker thread (daemon) |

---

## New Instance Variables

Ninguna. No se añaden atributos a `__init__`. El nuevo campo `data_source` se almacena únicamente en `self.backtest_state["form"]` (dict existente, ya inicializado en `__init__` línea ~159).

---

## Threading Analysis

`on_side_panel_event` y todos los métodos que invoca (`_on_backtest_run`, `_on_backtest_compare`) se ejecutan en el **callback thread** (`_callback_loop`). Este thread llama a `self.chart.run_script()` directamente, con `try/except Exception`, que es el patrón establecido en toda la clase.

`_run_backtest_worker` y `_run_backtest_comparison_worker` se ejecutan en hilos worker separados (daemon). Ellos llaman a `self._render_backtest_panel()` / `self._render_backtest_comparison_panel()` al finalizar, que a su vez llaman a `self.chart.run_script()`. Esto ya ocurre hoy — esta spec no añade nuevos `chart.run_script()` en ningún hilo nuevo.

`build_data_source()` y `resolve_symbol_for_request()` se llaman en el callback thread, antes de lanzar el worker. No hay acceso a GUI desde factory — es código Python puro que lee `symbols.json`.

**Confirmado**: no se añaden llamadas a `chart.run_script()` desde ningún hilo que no las haga ya.

---

## JavaScript Interaction Points

### 1. Inclusión del selector en el payload del botón "Ejecutar backtest"

- **Pattern**: JS → Python (vía `window.callbackFunction` existente)
- **Trigger**: click en `#tv-backtest-run`
- **Data crossing the boundary**: El campo `data_source: datasourceSel.value || "mt5"` se añade al objeto `request` JSON que ya se envía. El handler Python `_on_backtest_run` lo lee como `payload.get("data_source")`.
- **Handler registration**: sin cambio — sigue usando `state.handler + "_~_backtest_run;;;" + encodeURIComponent(JSON.stringify(request))` (línea ~5508–5510).
- **Brace budget**: 2 niveles de `{{ }}` (ya existente, sin cambio de profundidad).

### 2. Inclusión del selector en el payload del botón "Comparar estrategias"

- **Pattern**: JS → Python (vía `window.callbackFunction` existente)
- **Trigger**: click en `#tv-backtest-compare-btn`
- **Data crossing the boundary**: Ídem — `data_source: datasourceSel.value || "mt5"` se añade al objeto `request` JSON enviado a `_on_backtest_compare`.
- **Handler registration**: sin cambio — sigue usando `state.handler + "_~_backtest_compare;;;" + ...` (línea ~5730).
- **Brace budget**: 2 niveles de `{{ }}` (ya existente, sin cambio de profundidad).

### 3. Restauración del selector en `renderBacktestPanel`

- **Pattern**: Python → JS con JSON (payload ya existente `panel_json`)
- **Trigger**: llamada a `_render_backtest_panel()` (tras run o error)
- **Data crossing the boundary**: `panel_payload["form"]["data_source"]` (string `"mt5"` o `"dukascopy"`) se incluye en el dict `form` que ya viaja en `panel_json`. El JS lee `state.form.data_source` y asigna `datasourceSel.value`.
- **Brace budget**: sin cambio de profundidad respecto al `renderBacktestPanel` existente.

---

## Insertion Point Map

### A. HTML del selector — dentro de `backtestPanel.innerHTML` en `_build_side_panel`

**Ubicación**: línea **4882–4883** (inmediatamente después del cierre del `<div class="tv-backtest-field">` del campo "Símbolo", antes del `<div class="tv-backtest-field readonly">` del campo "Timeframe").

```
Línea 4880:     <div class="tv-backtest-field">
Línea 4881:         <label>Símbolo</label>
Línea 4882:         <select id="tv-backtest-symbol"></select>
Línea 4883:     </div>
                                    ← INSERTAR AQUÍ el nuevo campo
Línea 4884:     <div class="tv-backtest-field readonly">
Línea 4885:         <label>Timeframe</label>
Línea 4886:         <div class="tv-backtest-readonly" id="tv-backtest-timeframe">--</div>
Línea 4887:     </div>
```

**HTML exacto a insertar** (entre la línea 4883 y la 4884, como nueva línea dentro del template string):

```html
                    <div class="tv-backtest-field">
                        <label>Fuente de datos</label>
                        <select id="tv-backtest-datasource">
                            <option value="mt5">MT5</option>
                            <option value="dukascopy">Dukascopy</option>
                        </select>
                    </div>
```

Nota: El template es un backtick string de JS (dentro de un f-string Python). Las llaves `{` y `}` no aparecen en este bloque HTML — no hay riesgo de escape. La indentación debe seguir el patrón de 24 espacios usado por los campos adyacentes.

**Qué NO debe cambiar**: el `<div>` del campo "Símbolo" (líneas 4880–4883) y el `<div>` del campo "Timeframe" (líneas 4884–4887) no se tocan.

---

### B. `renderBacktestPanel` (JS) — obtener referencia al selector y restaurar su valor

**Ubicación**: dentro del bloque `window.renderBacktestPanel = (data) => {{ ... }}`, que empieza en línea ~5384 y cuya sección de `getElementById` se encuentra en líneas ~5397–5408.

**Cambio 1 — Añadir getElementById** (después de `const balanceEl = ...` en línea ~5403, antes de `const runBtn = ...` en línea ~5404):

```javascript
// INSERTAR entre línea 5403 y 5404:
const datasourceSel = document.getElementById("tv-backtest-datasource");
```

**Cambio 2 — Incluir datasourceSel en el guard de existencia** (línea ~5408):

```
// LÍNEA ACTUAL (~5408):
if (!strategySel || !symbolSel || !timeframeEl || !presetsEl || !startEl || !endEl || !balanceEl || !runBtn || !statusEl || !errorEl || !resultsEl) return;

// LÍNEA MODIFICADA:
if (!strategySel || !symbolSel || !datasourceSel || !timeframeEl || !presetsEl || !startEl || !endEl || !balanceEl || !runBtn || !statusEl || !errorEl || !resultsEl) return;
```

**Cambio 3 — Restaurar el valor del selector tras re-render** (después de `balanceEl.value = state.form.initial_balance || "";` en línea ~5472, antes de `updateTimeframe()` en línea ~5473):

```javascript
// INSERTAR entre línea 5472 y 5473:
datasourceSel.value = state.form.data_source || "mt5";
```

**Cambio 4 — Registrar onchange del selector** (después de `symbolSel.onchange = () => { ... };` en líneas ~5480–5482, antes de `startEl.onchange = ...` en línea ~5483):

```javascript
// INSERTAR entre línea 5482 y 5483:
datasourceSel.onchange = () => {{
    state.form.data_source = datasourceSel.value || "mt5";
}};
```

**Cambio 5 — Incluir `data_source` en el payload del botón "Ejecutar backtest"** (dentro del `runBtn.onclick`, líneas ~5499–5511, dentro del objeto `request`):

```
// OBJETO request ACTUAL (~5500–5507):
const request = {{
    strategy_key: state.form.strategy_key || "",
    symbol: state.form.symbol || "",
    preset: state.form.preset || "CUSTOM",
    start_date: startEl.value || "",
    end_date: endEl.value || "",
    initial_balance: balanceEl.value || "",
}};

// OBJETO request MODIFICADO — añadir data_source como último campo antes del cierre:
const request = {{
    strategy_key: state.form.strategy_key || "",
    symbol: state.form.symbol || "",
    preset: state.form.preset || "CUSTOM",
    start_date: startEl.value || "",
    end_date: endEl.value || "",
    initial_balance: balanceEl.value || "",
    data_source: datasourceSel.value || "mt5",
}};
```

**Qué NO debe cambiar**: La línea `runBtn.disabled = ...` (línea ~5497), el handler `window.callbackFunction(...)` (línea ~5509), y la estructura de los onchange existentes.

---

### C. Compare button onclick — añadir `data_source` al payload de comparación

**Ubicación**: dentro del `compareBtn.addEventListener("click", () => {{ ... }})` en líneas ~5703–5733. El objeto `request` se construye en líneas ~5721–5728.

```
// OBJETO request ACTUAL (~5721–5728):
const request = {{
    strategy_keys:   selectedKeys,
    symbol:          state.form.symbol || "",
    preset:          state.form.preset || "CUSTOM",
    start_date:      (document.getElementById("tv-backtest-start") || {{}}).value || "",
    end_date:        (document.getElementById("tv-backtest-end") || {{}}).value || "",
    initial_balance: (document.getElementById("tv-backtest-balance") || {{}}).value || "",
}};

// OBJETO request MODIFICADO — añadir data_source:
const request = {{
    strategy_keys:   selectedKeys,
    symbol:          state.form.symbol || "",
    preset:          state.form.preset || "CUSTOM",
    start_date:      (document.getElementById("tv-backtest-start") || {{}}).value || "",
    end_date:        (document.getElementById("tv-backtest-end") || {{}}).value || "",
    initial_balance: (document.getElementById("tv-backtest-balance") || {{}}).value || "",
    data_source:     (document.getElementById("tv-backtest-datasource") || {{}}).value || "mt5",
}};
```

Nota: Se usa `getElementById` inline en vez de la variable local `datasourceSel` porque este handler es un listener separado que se registra en un bloque `if (compareBtn && !compareBtn.dataset.compareBound)` — puede que `datasourceSel` no esté en scope si el renderizado del panel se re-ejecuta. Usar `getElementById` inline es más seguro y sigue el patrón de `start_date`/`end_date`/`initial_balance` en el mismo bloque.

**Qué NO debe cambiar**: la validación de `selectedKeys.length < 2` (línea ~5711), el `window.callbackFunction(...)` (línea ~5730).

---

### D. `_get_backtest_form_state` — añadir `data_source` al form dict

**Ubicación**: método en líneas 753–786. El dict `form` que se construye y retorna está en líneas 777–784.

**Cambio**: añadir lectura y validación de `data_source` antes de construir el dict final, y añadir `"data_source"` al dict.

**Pseudocode del cambio** (líneas 777–784 actuales → modificadas):

```python
# ANTES de construir el dict final (línea ~777), añadir:
data_source = str(form.get("data_source") or "mt5").lower()
if data_source not in ("mt5", "dukascopy"):
    data_source = "mt5"

# Dict form ACTUAL (líneas 777–784):
form = {
    "strategy_key": strategy_key,
    "symbol": symbol,
    "preset": preset,
    "start_date": start_date,
    "end_date": end_date,
    "initial_balance": initial_balance,
}

# Dict form MODIFICADO — añadir data_source:
form = {
    "strategy_key": strategy_key,
    "symbol": symbol,
    "preset": preset,
    "start_date": start_date,
    "end_date": end_date,
    "initial_balance": initial_balance,
    "data_source": data_source,
}
```

**Qué NO debe cambiar**: las líneas 753–776 (resolución de estrategia, símbolo, preset, fechas, balance) y la línea `self.backtest_state["form"] = form` (línea 785).

---

### E. `_on_backtest_run` — leer `data_source`, llamar factory, resolver símbolo

**Ubicación**: método en líneas 873–962. El punto de inserción es después de la validación de fechas (línea ~930) y antes de la construcción del dict `self.backtest_state["form"]` (línea ~931).

**Cambio 1**: añadir lectura y normalización de `source_name` después de la línea que lee `symbol` (~línea 903):

```python
# INSERTAR después de línea ~907 (cierre del bloque if not symbol: return):
source_name = str(payload.get("data_source") or "mt5").lower()
if source_name not in ("mt5", "dukascopy"):
    source_name = "mt5"
```

**Cambio 2**: añadir llamada al factory e interceptar `ValueError`, después de la validación de fechas y antes del bloque `self.backtest_state["form"] = ...` (entre línea ~930 y ~931):

```python
# INSERTAR entre la validación de fechas (~línea 930) y el bloque form (~línea 931):
try:
    from src.data.factory import build_data_source, resolve_symbol_for_request
    data_source = build_data_source(source_name, symbol)
    request_symbol = resolve_symbol_for_request(source_name, symbol)
except ValueError as e:
    self.backtest_state["error"] = str(e)
    self._render_backtest_panel()
    return
```

**Cambio 3**: en el bloque `self.backtest_state["form"] = { ... }` (líneas ~931–938), añadir `"data_source": source_name`:

```python
self.backtest_state["form"] = {
    "strategy_key": entry["key"],
    "symbol": symbol,
    "preset": str(payload.get("preset") or "CUSTOM").upper(),
    "start_date": str(payload.get("start_date") or ""),
    "end_date": str(payload.get("end_date") or ""),
    "initial_balance": f"{initial_balance:.2f}",
    "data_source": source_name,              # NUEVO
}
```

**Cambio 4**: en el dict `request` (líneas ~942–955), reemplazar `"symbol": symbol` por `"symbol": request_symbol`, y añadir `"data_provider": source_name`:

```python
request = {
    "strategy_key": entry["key"],
    "strategy_label": entry["label"],
    "module": entry.get("module_obj"),
    "symbol": request_symbol,                # MODIFICADO
    "data_provider": source_name,            # NUEVO
    "timeframe_value": entry.get("timeframe_value"),
    "start_date": start_date,
    "end_date": end_date,
    "initial_balance": initial_balance,
    "warmup_bars": max(int(getattr(config, "BARS_HISTORY", 500) or 500), 500),
    "lot": float(getattr(config, "LOT", 0.01) or 0.01),
    "sl_points": float(getattr(config, "SL_POINTS", 0.0) or 0.0),
    "tp_points": float(getattr(config, "TP_POINTS", 0.0) or 0.0),
}
```

**Cambio 5**: en `threading.Thread(...)` (líneas ~957–962), pasar `data_source` a `args`:

```python
self.backtest_thread = threading.Thread(
    target=self._run_backtest_worker,
    args=(request, data_source),             # MODIFICADO
    daemon=True,
)
```

**Qué NO debe cambiar**: todas las validaciones anteriores (empty payload, already running, JSON parse error, strategy not found, symbol empty, balance ≤ 0, dates) — líneas 874–930.

---

### F. `_run_backtest_worker` — firma y llamada a `run_backtest`

**Ubicación**: líneas 859–871.

**Cambio**: añadir parámetro `data_source=None` a la firma y pasarlo a `run_backtest`:

```python
# FIRMA ACTUAL (línea 859):
def _run_backtest_worker(self, request: dict):
    try:
        result = run_backtest(request)

# FIRMA MODIFICADA:
def _run_backtest_worker(self, request: dict, data_source=None):
    try:
        result = run_backtest(request, data_source=data_source)
```

**Qué NO debe cambiar**: el resto del método (líneas 863–871).

---

### G. `_on_backtest_compare` — mismo patrón que `_on_backtest_run`

**Ubicación**: líneas 964–1057. Puntos de inserción análogos a los de `_on_backtest_run`.

**Cambio 1**: añadir lectura de `source_name` después de la lectura de `symbol` (~línea 1009):

```python
# INSERTAR después de línea ~1013 (cierre del bloque if not symbol: return):
source_name = str(payload.get("data_source") or "mt5").lower()
if source_name not in ("mt5", "dukascopy"):
    source_name = "mt5"
```

**Cambio 2**: añadir llamada al factory antes del bloque `request` (~línea 1037), después de la validación de fechas (~línea 1035):

```python
# INSERTAR entre línea ~1035 y ~1037:
try:
    from src.data.factory import build_data_source, resolve_symbol_for_request
    data_source = build_data_source(source_name, symbol)
    request_symbol = resolve_symbol_for_request(source_name, symbol)
except ValueError as e:
    self.backtest_state["comparison_error"] = str(e)
    self._render_backtest_comparison_panel()
    return
```

**Cambio 3**: en el dict `request` (líneas ~1037–1047), sustituir `"symbol": symbol` por `"symbol": request_symbol`:

```python
request = {
    "symbol":          request_symbol,       # MODIFICADO
    "data_provider":   source_name,          # NUEVO
    "start_date":      start_date,
    "end_date":        end_date,
    "initial_balance": initial_balance,
    "strategies":      strategies,
    "warmup_bars":     max(int(getattr(config, "BARS_HISTORY", 500) or 500), 500),
    "lot":             float(getattr(config, "LOT", 0.01) or 0.01),
    "sl_points":       float(getattr(config, "SL_POINTS", 0.0) or 0.0),
    "tp_points":       float(getattr(config, "TP_POINTS", 0.0) or 0.0),
}
```

**Cambio 4**: en `threading.Thread(...)` (líneas ~1052–1057), añadir `data_source` a `args`:

```python
self.comparison_thread = threading.Thread(
    target=self._run_backtest_comparison_worker,
    args=(request, data_source),             # MODIFICADO
    daemon=True,
)
```

**Qué NO debe cambiar**: las validaciones de `strategy_keys`, `strategies`, `symbol`, `initial_balance`, fechas — líneas 965–1035.

---

### H. `_run_backtest_comparison_worker` — firma y llamada a `run_backtest_comparison`

**Ubicación**: líneas 1059–1072.

**Cambio**: análogo a `_run_backtest_worker`:

```python
# FIRMA ACTUAL (línea 1059):
def _run_backtest_comparison_worker(self, request: dict):
    try:
        result = run_backtest_comparison(request)

# FIRMA MODIFICADA:
def _run_backtest_comparison_worker(self, request: dict, data_source=None):
    try:
        result = run_backtest_comparison(request, data_source=data_source)
```

**Qué NO debe cambiar**: el resto del método (líneas 1063–1072).

---

## Error Handling: símbolo sin mapping Dukascopy

Cuando `build_data_source("dukascopy", symbol)` lanza `ValueError` (símbolo no en `symbols.json`, o sin `providers.dukascopy`, o `dukascopy-python` no instalado):

- En `_on_backtest_run`: se asigna `self.backtest_state["error"] = str(e)` y se llama `self._render_backtest_panel()`. El error se muestra en el elemento `#tv-backtest-error` (inline, en rojo, ya soportado por el CSS `tv-backtest-error` existente). El hilo worker NO se lanza.
- En `_on_backtest_compare`: ídem con `self.backtest_state["comparison_error"]` y `self._render_backtest_comparison_panel()`. El error aparece en el mismo `#tv-backtest-error` que `renderBacktestComparison` actualiza.
- En ambos casos, el selector `#tv-backtest-datasource` permanece con el valor elegido (se restaura en el re-render via `state.form.data_source`).

No se usa `show_toast`. La zona de error existente es suficiente y coherente con el comportamiento de todos los demás errores del formulario.

---

## Invariant Checklist

- [x] No se añaden llamadas a `chart.run_script()` desde ningún hilo nuevo — el patrón existente (callback thread + worker thread) se preserva sin cambio.
- [x] El selector `#tv-backtest-datasource` ya existe en el DOM cuando `renderBacktestPanel` lo lee (`getElementById`), porque el HTML se inyecta en el template estático antes de que `renderBacktestPanel` se ejecute.
- [x] No se añaden nuevas referencias a `config` — `build_data_source` y `resolve_symbol_for_request` reciben sus parámetros del caller, no leen `config` directamente.
- [x] No se añaden nuevas variables de instancia en `__init__` — `data_source` es local al handler.
- [x] `self.strategy_registry` no es leído ni escrito por ningún cambio de esta spec.
- [x] El import `from src.data.factory import build_data_source, resolve_symbol_for_request` se hace en el cuerpo del handler (inline, en el `try` block), siguiendo el patrón de imports tardíos ya usado en otros métodos del archivo. Esto evita error de importación al arrancar si `factory.py` aún no existe (TASK-051 no está done).
- [x] Ningún handler JS→Python nuevo — no hay colisión de nombres.
- [x] MT5 sigue siendo el default (`source_name = "mt5"` cuando el campo no está en el payload) — backward compatibility garantizada.

---

## Notas / Ambigüedades

### 1. Import inline vs. import at top of file

El import de `build_data_source` y `resolve_symbol_for_request` se especifica como inline (dentro del `try` block del handler). Esto es intencional: `factory.py` es creado por TASK-051, que puede no estar done cuando Felix implemente TASK-052. El import inline evita que la app falle al arrancar si el archivo aún no existe. Cuando TASK-051 esté done, Alex puede moverlo al top del archivo si lo prefiere — eso es decisión de TASK-051.

### 2. `datasourceSel` en compare button listener

El compare button usa un `if (!compareBtn.dataset.compareBound)` guard para registrar el listener solo una vez. Dentro del closure de ese listener, `datasourceSel` podría no ser la misma instancia que la creada en el render posterior. Por eso se especifica `document.getElementById("tv-backtest-datasource")` inline en el payload de comparación, siguiendo el patrón de los otros campos del mismo bloque (`tv-backtest-start`, `tv-backtest-end`, `tv-backtest-balance`). Felix debe seguir esta decisión y NO usar la variable `datasourceSel` capturada del `renderBacktestPanel` scope.

### 3. `_get_backtest_payload` no incluye `data_source` explícitamente

`_get_backtest_payload` delega en `_get_backtest_form_state` para el dict `form`. Una vez que `_get_backtest_form_state` devuelve `data_source` en el form, el campo viaja automáticamente en `panel_payload["form"]["data_source"]` hacia JS. No es necesario modificar `_get_backtest_payload` directamente.

### 4. `_render_backtest_comparison_panel` no incluye `form` en el payload

`_render_backtest_comparison_panel` (líneas 1120–1137) envía solo `comparison_running`, `comparison_result`, `comparison_error`. No envía `form`. Por tanto, `renderBacktestComparison` no restaura el selector. Esto es aceptable: el modo "Comparar" comparte el mismo formulario visual con el modo "Individual" (mismo panel HTML), y `renderBacktestPanel` es el que gestiona la restauración del form. La única consecuencia es que si se dispara un error de Dukascopy en modo compare, el formulario no se re-renderiza completamente — solo el área de error. El selector queda con el valor que el usuario eligió (no hay re-render del form). Este comportamiento es correcto.

### 5. `data_provider` en el request vs `data_source` en el form

Daniel especifica que el request dict incluye `"data_provider": source_name`. Este campo es informacional para el resultado del backtest (puede aparecer en los metadatos del resultado). No tiene impacto en el comportamiento del motor (`backtesting/runtime.py` no lo lee). Felix puede añadirlo al dict `request` sin preocupación.
