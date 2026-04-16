# GUI Change Spec: Quick Params Panel por Estrategia

**By**: Grace
**Date**: 2026-04-14
**Task**: TASK-043
**Status**: ready

---

## Backend Summary

Daniel's TASK-042 spec adds three new fields to each strategy entry dict (populated by Alex in TASK-044):

- `entry["params_schema"]` — `dict | None`. Keys are param names (snake_case). Each value is `{"label": str, "type": "int"|"float", "default": number, "min": number, "max": number}`. `None` means the module has no `PARAMS` attribute. An empty dict `{}` means `PARAMS = {}` was declared (valid, no editable params).
- `entry["params_values"]` — `dict`. Keys = same as `params_schema`. Values = current merged scalars (defaults overridden by `.params.json`). Empty `{}` when no schema.
- `entry["accepts_params"]` — `bool`. Not needed by GUI; backend only.

**GUI rule derived from schema**: A "Params" button is shown if and only if `params_schema is not None and len(params_schema) > 0`.

**Save path**: GUI writes `{"param_key": scalar, ...}` to `<strategy_dir>/<strategy_key>.params.json`, then calls `_load_strategy_entry(entry)` to reload the module (which re-reads `.params.json`). This is identical to the reload path already used by `_on_strategy_builder_save`.

**File location for `.params.json`**: Same directory as the strategy `.py` file, using the `.py` filename stem — e.g., `strategies/strategy_primera_estrategia.params.json`. This matches Daniel's backend exactly. Felix must derive the path from `entry["module_obj"].__file__` (not from `key`):
```python
module_obj = entry.get("module_obj")
module_file = getattr(module_obj, "__file__", None) if module_obj else None
if module_file and not module_file.startswith("<"):
    params_json_path = os.path.splitext(module_file)[0] + ".params.json"
else:
    params_json_path = os.path.join(strategy_dir, f"{key}.params.json")
```
Using `key` directly (e.g., `primera_estrategia.params.json`) does NOT match the backend which expects `strategy_primera_estrategia.params.json`.

---

## Summary

This change adds a "Params" button to each strategy row in the side panel when that strategy exposes editable parameters via a `PARAMS` dict. Clicking the button opens a modal overlay (`openParamsPanel`) with auto-generated numeric inputs (int/float), min/max constraints, and a Save action. Save writes the user's values to a `.params.json` file and triggers a strategy reload. The existing "Editar" button (Strategy Builder) is not removed or modified. No new tabs, no registry structure changes, no threading changes to the bot loop.

---

## Affected Methods

| Method | File location (approx line) | Change type | Threading context |
|--------|-----------------------------|-------------|-------------------|
| `_get_strategy_payload()` | ~L665 | modify | callback-loop (called from `_render_strategy_panel`, which is called from main thread and from callback-loop handlers) |
| `renderBuilderButtons` (JS function, inside `_build_strategy_builder_ui`) | ~L2134 | modify | JS only — injected once at setup |
| `_build_strategy_builder_ui()` | ~L1876 | modify — add `openParamsPanel`, `closeParamsPanel` JS functions and CSS | callback-loop (via setup_side_panel, but idempotency guard covers re-entry) |
| `on_side_panel_event()` | ~L5945 | modify — add two new action branches | callback-loop |
| `_on_strategy_params_open(key)` | after ~L6009 | new method | callback-loop |
| `_on_strategy_params_save(key, overrides_json)` | after `_on_strategy_params_open` | new method | callback-loop |

---

## New Instance Variables

None. No new `self.*` attributes are required. The params data lives in the existing registry entry dicts (`entry["params_schema"]`, `entry["params_values"]`).

---

## Threading Analysis

`on_side_panel_event` and all methods it calls are invoked from the `_callback_loop` thread (line ~4275). This thread drains `Chart.WV.emit_queue` and calls handlers directly via `func(*args)`. The `_callback_loop` thread is the thread that issued `chart.show()` in the original design — or at minimum it is the same thread that runs all other `on_*` side-panel handlers without any queue indirection.

**Evidence**: `_on_strategy_builder_open` (line ~6053) and `_on_strategy_builder_save` (line ~6288) both call `self.chart.run_script(...)` directly, with no queue push. They are called from `on_side_panel_event`. This confirms that all `on_side_panel_event` branches run in a context where `chart.run_script()` is safe.

**Conclusion for this spec**: `_on_strategy_params_open` and `_on_strategy_params_save` may call `self.chart.run_script(...)` directly. No callback queue indirection is needed.

Confirmed: no `chart.run_script()` call is introduced in the bot-loop thread or the quote thread.

---

## JavaScript Interaction Points

### 1. Python → JS: open params panel

- **Pattern**: Python → JS with JSON
- **Trigger**: `_on_strategy_params_open(key)` is called; it reads `entry["params_schema"]` and `entry["params_values"]` and calls `chart.run_script`
- **Data crossing the boundary**: JSON payload with schema and current values (see pseudocode below)
- **Brace budget**: 2 levels — outer IIFE `(function() {{ }})();`, then `if (window.openParamsPanel) {{ }}`. No deeper nesting needed in Python; JS function body uses regular braces since it is not inside an f-string.
- **Constraints**: payload is `json.dumps(...)` before f-string insertion — safe from brace-escaping issues.

```
payload = json.dumps({
    "key": key,
    "label": entry["label"],
    "schema": entry["params_schema"],   # {param_key: {label, type, default, min, max}}
    "values": entry["params_values"],   # {param_key: current_scalar}
    "handler": self.side_panel_handler,
})
self.chart.run_script(f"""
    ;(function() {{
        const payload = {payload};
        if (window.openParamsPanel) {{
            window.openParamsPanel(payload);
        }}
    }})();
""")
```

### 2. JS → Python: save params

- **Pattern**: JS → Python
- **Trigger**: user clicks "Guardar" in the params modal
- **Data crossing the boundary**: `strategy_params_save;;;{key};;;{json_de_overrides}` — key is URL-encoded, overrides is URL-encoded JSON string of `{param_key: scalar}` pairs
- **Handler registration**: uses the existing `self.side_panel_handler` (already registered as `on_side_panel_event`). No new handler registration needed.
- **JS call**:
  ```javascript
  const overridesJson = encodeURIComponent(JSON.stringify(overridesObj));
  const encodedKey = encodeURIComponent(String(payload.key || ""));
  window.callbackFunction(handler + "_~_strategy_params_save;;;" + encodedKey + ";;;" + overridesJson);
  ```
- **Constraints**: key and JSON are both URL-encoded. Python side uses `unquote()` on each arg. JSON string is parsed with `json.loads()` after unquoting.

### 3. JS → Python: open params (button click)

- **Pattern**: JS → Python
- **Trigger**: user clicks "Params" button in strategy row
- **Data crossing the boundary**: `strategy_params_open;;;{key}` (key URL-encoded)
- **Handler registration**: uses existing `self.side_panel_handler`. No new handler.
- **JS call** (inside `renderBuilderButtons`):
  ```javascript
  window.callbackFunction(handler + "_~_strategy_params_open;;;" + encodeURIComponent(String(strategy.key || "")));
  ```

### 4. Python → JS: confirmation message after save

- **Pattern**: Python → JS with JSON (simple string payload)
- **Trigger**: end of `_on_strategy_params_save` on success
- **Data**: success message string, JSON-encoded
- **Brace budget**: 2 levels (IIFE + if-guard)
- **Mechanism**: call `window.setParamsMessage(msg)` — a new JS function defined in `_build_strategy_builder_ui`. Displays a temporary message inside the params modal or as an inline status line.

---

## Insertion Point Map

### A. `_get_strategy_payload()` — add `has_params` field (~L692)

**Location**: Inside the `payload.append({...})` block, after the `"has_config": has_config,` line (line ~702).

**What changes**: Add one new key `"has_params"` to each strategy dict in the payload. Value is `True` if `entry.get("params_schema")` is a non-empty dict, `False` otherwise.

**What must NOT change**: All existing keys (`key`, `label`, `module`, `enabled`, `timeframe`, `magic`, `status`, `last_run`, `has_config`) and their computation logic.

**Pseudocode**:
```
params_schema = entry.get("params_schema")
has_params = isinstance(params_schema, dict) and len(params_schema) > 0

payload.append({
    # ... all existing keys unchanged ...
    "has_config": has_config,
    "has_params": has_params,   # NEW — added as last key
})
```

---

### B. `renderBuilderButtons` JS function — add "Params" button (~L2134)

**Location**: Inside `_build_strategy_builder_ui()`, inside the `window.renderBuilderButtons = (data) => { ... }` function body (lines ~2134–2155). The new "Params" button logic is appended **after** the existing "Editar" button block, still inside the `strategies.forEach(...)` loop.

**What changes**: After the existing `editBtn` block (which guards on `strategy.has_config`), add a parallel block that guards on `strategy.has_params`. Creates a `"Params"` button with the same structural pattern as `editBtn`. Appends to the same `.tv-strategy-right` container.

**What must NOT change**: The `editBtn` block must remain exactly as-is. The `if (!strategy.has_config) return;` guard at the top of the forEach must NOT be changed to cover the Params button — Params has its own guard below.

**Idempotency**: `renderBuilderButtons` is called every time `_render_strategy_panel` runs. The existing `editBtn` uses `.querySelector(".tv-builder-edit-btn")` to skip re-insertion. The new Params button must use a distinct class guard: check `row.querySelector(".tv-params-btn")` before creating it.

**Pseudocode** (JS, append inside the `strategies.forEach` callback after the editBtn block):
```javascript
// NEW: Params button — shown when strategy has editable params
if (strategy.has_params) {
    const row2 = document.querySelector(`.tv-strategy-item[data-key="${strategy.key}"]`);
    if (row2 && !row2.querySelector(".tv-params-btn")) {
        const paramsBtn = document.createElement("button");
        paramsBtn.type = "button";
        paramsBtn.className = "tv-params-btn";
        paramsBtn.innerText = "Params";
        paramsBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const handler = (data && data.handler) ? data.handler : "";
            const key = encodeURIComponent(String(strategy.key || ""));
            window.callbackFunction(handler + "_~_strategy_params_open;;;" + key);
        });
        const right2 = row2.querySelector(".tv-strategy-right");
        if (right2) right2.appendChild(paramsBtn);
    }
}
```

Note: `row` is already the correct row element inside the original editBtn block, but the editBtn block returns early (`return`) if `!strategy.has_config`. The Params button block must NOT be placed inside that early-return path — it must be its own separate block, still inside the forEach but after the editBtn block's closing brace.

**Revised structure** (full forEach rewrite — Felix must rewrite the entire forEach body to remove the early `return` at the top):

The current `renderBuilderButtons` forEach starts with `if (!strategy.has_config) return;`. This `return` also suppresses the Params button for strategies without a Builder `.json`. Felix must restructure as follows:

```javascript
strategies.forEach((strategy) => {
    const row = document.querySelector(`.tv-strategy-item[data-key="${strategy.key}"]`);
    if (!row) return;  // keep this guard

    // "Editar" button — Builder-generated only
    if (strategy.has_config && !row.querySelector(".tv-builder-edit-btn")) {
        const editBtn = document.createElement("button");
        editBtn.type = "button";
        editBtn.className = "tv-builder-edit-btn";
        editBtn.innerText = "Editar";
        editBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const handler = (data && data.handler) ? data.handler : "";
            const key = encodeURIComponent(String(strategy.key || ""));
            window.callbackFunction(handler + "_~_strategy_builder_open;;;" + key);
        });
        const right = row.querySelector(".tv-strategy-right");
        if (right) right.appendChild(editBtn);
    }

    // "Params" button — any strategy with non-empty PARAMS
    if (strategy.has_params && !row.querySelector(".tv-params-btn")) {
        const paramsBtn = document.createElement("button");
        paramsBtn.type = "button";
        paramsBtn.className = "tv-params-btn";
        paramsBtn.innerText = "Params";
        paramsBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const handler = (data && data.handler) ? data.handler : "";
            const key = encodeURIComponent(String(strategy.key || ""));
            window.callbackFunction(handler + "_~_strategy_params_open;;;" + key);
        });
        const right = row.querySelector(".tv-strategy-right");
        if (right) right.appendChild(paramsBtn);
    }
});
```

---

### C. `_build_strategy_builder_ui()` — add `openParamsPanel`, `closeParamsPanel`, `setParamsMessage` JS functions and CSS (~L1876)

**Location**: At the end of the `chart.run_script(...)` block inside `_build_strategy_builder_ui()`. The existing script block ends just before `'''` at line ~1874 (current end of the method). New JS is appended **inside the same `run_script` call**, before the closing `'''`.

**Important**: the existing `chart.run_script(...)` in `_build_strategy_builder_ui` starts at line ~1878 with `'''` (no f-string prefix — it is a plain triple-quoted string, not an f-string). The new code to add is also plain JS with no Python interpolation, so it remains a plain string. Felix must confirm whether the existing block is an f-string or plain string before inserting.

**Idempotency**: The function opens with `if (document.getElementById("tv-builder-form-view")) return;`. The new JS functions (`openParamsPanel`, `closeParamsPanel`, `setParamsMessage`) and CSS would be skipped on subsequent calls because of this guard. This is correct — they are set up once.

**What changes**: Three new JS window functions and one CSS block injected inside the existing `_build_strategy_builder_ui` script.

**What must NOT change**: All existing JS in `_build_strategy_builder_ui`. The guard `if (document.getElementById("tv-builder-form-view")) return;` must remain as the first statement.

**CSS additions** (injected as part of the same `<style>` block already created in `_build_strategy_builder_ui`, or as a new `<style>` element — Felix checks which approach is already used):

```css
/* Quick Params modal overlay */
#tv-params-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.55);
    z-index: 9000;
    display: flex;
    align-items: center;
    justify-content: center;
}
#tv-params-panel {
    background: #1e2230;
    border: 1px solid #333;
    border-radius: 6px;
    padding: 20px;
    min-width: 320px;
    max-width: 480px;
    max-height: 80vh;
    overflow-y: auto;
    color: #d1d4dc;
    font-family: inherit;
    font-size: 13px;
}
#tv-params-panel h3 {
    margin: 0 0 14px 0;
    font-size: 14px;
    color: #e0e3ea;
}
.tv-params-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
    gap: 8px;
}
.tv-params-row label {
    flex: 1;
    color: #9aa0ab;
}
.tv-params-row input[type="number"] {
    width: 110px;
    background: #131722;
    border: 1px solid #444;
    border-radius: 3px;
    color: #d1d4dc;
    padding: 4px 6px;
    font-size: 13px;
}
#tv-params-actions {
    display: flex;
    gap: 8px;
    margin-top: 16px;
    justify-content: flex-end;
}
#tv-params-actions button {
    padding: 6px 16px;
    border-radius: 4px;
    border: none;
    cursor: pointer;
    font-size: 13px;
}
#tv-params-save-btn {
    background: #2962ff;
    color: #fff;
}
#tv-params-cancel-btn {
    background: #2a2e39;
    color: #9aa0ab;
}
#tv-params-message {
    font-size: 12px;
    color: #26a69a;
    margin-top: 8px;
    min-height: 16px;
}
.tv-params-btn {
    margin-left: 4px;
    padding: 2px 8px;
    font-size: 11px;
    background: #1a3a5e;
    color: #90b0e0;
    border: 1px solid #2962ff44;
    border-radius: 3px;
    cursor: pointer;
}
.tv-params-btn:hover {
    background: #2962ff;
    color: #fff;
}
```

**JS pseudocode — `window.openParamsPanel(payload)`**:

```javascript
window.openParamsPanel = (payload) => {
    // payload: { key, label, schema, values, handler }
    // schema: { param_key: { label, type, default, min, max } }
    // values: { param_key: current_value }

    // Remove any existing overlay first (idempotency)
    const existing = document.getElementById("tv-params-overlay");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "tv-params-overlay";

    const panel = document.createElement("div");
    panel.id = "tv-params-panel";

    const title = document.createElement("h3");
    title.innerText = "Parámetros: " + (payload.label || payload.key);
    panel.appendChild(title);

    const schema = payload.schema || {};
    const values = payload.values || {};

    // Build one input row per param
    Object.keys(schema).forEach((paramKey) => {
        const def = schema[paramKey];
        const currentVal = (paramKey in values) ? values[paramKey] : def.default;

        const row = document.createElement("div");
        row.className = "tv-params-row";

        const lbl = document.createElement("label");
        lbl.innerText = def.label || paramKey;
        lbl.htmlFor = "tv-param-" + paramKey;

        const inp = document.createElement("input");
        inp.type = "number";
        inp.id = "tv-param-" + paramKey;
        inp.dataset.paramKey = paramKey;
        inp.dataset.paramType = def.type;
        inp.min = String(def.min);
        inp.max = String(def.max);
        inp.step = (def.type === "int") ? "1" : "any";
        inp.value = String(currentVal);

        row.appendChild(lbl);
        row.appendChild(inp);
        panel.appendChild(row);
    });

    // Message area
    const msgEl = document.createElement("div");
    msgEl.id = "tv-params-message";
    panel.appendChild(msgEl);

    // Action buttons
    const actions = document.createElement("div");
    actions.id = "tv-params-actions";

    const cancelBtn = document.createElement("button");
    cancelBtn.id = "tv-params-cancel-btn";
    cancelBtn.innerText = "Cancelar";
    cancelBtn.addEventListener("click", () => {
        if (window.closeParamsPanel) window.closeParamsPanel();
    });

    const saveBtn = document.createElement("button");
    saveBtn.id = "tv-params-save-btn";
    saveBtn.innerText = "Guardar";
    saveBtn.addEventListener("click", () => {
        // Collect current input values
        const overrides = {};
        panel.querySelectorAll("input[data-param-key]").forEach((inp) => {
            const k = inp.dataset.paramKey;
            const t = inp.dataset.paramType;
            let v = parseFloat(inp.value);
            if (isNaN(v)) return;
            // Clamp to [min, max]
            const minV = parseFloat(inp.min);
            const maxV = parseFloat(inp.max);
            if (!isNaN(minV) && v < minV) v = minV;
            if (!isNaN(maxV) && v > maxV) v = maxV;
            // Keep int type
            if (t === "int") v = Math.round(v);
            overrides[k] = v;
        });
        const handler = payload.handler || "";
        const encodedKey = encodeURIComponent(String(payload.key || ""));
        const overridesJson = encodeURIComponent(JSON.stringify(overrides));
        window.callbackFunction(handler + "_~_strategy_params_save;;;" + encodedKey + ";;;" + overridesJson);
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    panel.appendChild(actions);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    // Click outside overlay to close
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) {
            if (window.closeParamsPanel) window.closeParamsPanel();
        }
    });
};
```

**JS pseudocode — `window.closeParamsPanel()`**:

```javascript
window.closeParamsPanel = () => {
    const overlay = document.getElementById("tv-params-overlay");
    if (overlay) overlay.remove();
};
```

**JS pseudocode — `window.setParamsMessage(msg)`**:

```javascript
window.setParamsMessage = (msg) => {
    const msgEl = document.getElementById("tv-params-message");
    if (msgEl) msgEl.innerText = msg || "";
};
```

---

### D. `on_side_panel_event()` — add two new action branches (~L6009)

**Location**: At the end of `on_side_panel_event`, after the last `if action == "strategy_builder_save"` block (line ~6009), before the method ends.

**What changes**: Two new `if` branches.

**What must NOT change**: All existing branches. Order of existing branches is unchanged.

**Pseudocode**:
```python
if action == "strategy_params_open" and args:
    key = unquote(args[0]) if len(args) > 0 else ""
    self._on_strategy_params_open(key)
    return
if action == "strategy_params_save" and args:
    key = unquote(args[0]) if len(args) > 0 else ""
    overrides_json = unquote(args[1]) if len(args) > 1 else ""
    self._on_strategy_params_save(key, overrides_json)
    return
```

---

### E. `_on_strategy_params_open(key)` — new method

**Location**: After the closing of `on_side_panel_event` (line ~6010), before `_toggle_strategy_run` (line ~6011). Insert immediately after the last line of `on_side_panel_event`.

**Threading context**: callback-loop — may call `chart.run_script()` directly.

**Pseudocode**:
```python
def _on_strategy_params_open(self, key: str):
    # esta funcion sirve para abrir el panel de edición rápida de parámetros.
    key = (key or "").strip()
    entry = self._get_strategy_entry(key)
    if not entry:
        # Silent no-op — key not found
        return

    params_schema = entry.get("params_schema")
    if not isinstance(params_schema, dict) or len(params_schema) == 0:
        # Should not happen (button is hidden when no schema), but guard anyway
        return

    params_values = entry.get("params_values") or {}

    payload = json.dumps({
        "key": key,
        "label": entry.get("label") or key,
        "schema": params_schema,
        "values": params_values,
        "handler": self.side_panel_handler,
    })
    self.chart.run_script(f"""
        ;(function() {{
            const payload = {payload};
            if (window.openParamsPanel) {{
                window.openParamsPanel(payload);
            }}
        }})();
    """)
```

---

### F. `_on_strategy_params_save(key, overrides_json)` — new method

**Location**: Immediately after `_on_strategy_params_open` (new method E above).

**Threading context**: callback-loop — may call `chart.run_script()` directly.

**Save logic — Track A (Builder-generated) vs Track B (manual)**:

Daniel's spec clarifies that from the GUI's perspective, there is only ONE save path: write `<key>.params.json` to the strategy directory and call `_load_strategy_entry(entry)`. The distinction between "Builder-generated" and "manual" is purely a backend concern (whether the engine calls `generate_strategy_file` again). The GUI never needs to call `generate_strategy_file` for a params-only change — the backend picks up `.params.json` at reload time via `_load_strategy_params`. Felix does NOT need to implement Track A/B branching.

**Pseudocode**:
```python
def _on_strategy_params_save(self, key: str, overrides_json: str):
    # esta funcion sirve para guardar parámetros editados de estrategia.
    key = (key or "").strip()
    entry = self._get_strategy_entry(key)
    if not entry:
        return

    params_schema = entry.get("params_schema")
    if not isinstance(params_schema, dict) or len(params_schema) == 0:
        return

    overrides_json = (overrides_json or "").strip()
    try:
        overrides = json.loads(overrides_json)
    except Exception:
        overrides = {}

    if not isinstance(overrides, dict):
        overrides = {}

    # Validate and clamp each override against schema bounds
    validated = {}
    for param_key, value in overrides.items():
        schema_entry = params_schema.get(param_key)
        if not schema_entry:
            continue
        type_str = schema_entry.get("type", "float")
        min_val = schema_entry.get("min")
        max_val = schema_entry.get("max")
        try:
            if type_str == "int":
                coerced = int(round(float(value)))
            else:
                coerced = float(value)
        except (TypeError, ValueError):
            continue
        if min_val is not None:
            coerced = max(min_val, coerced)
        if max_val is not None:
            coerced = min(max_val, coerced)
        validated[param_key] = coerced

    # Derive .params.json path from module file (must match Daniel's backend)
    # e.g., strategy_primera_estrategia.py → strategy_primera_estrategia.params.json
    strategy_dir = self._get_strategy_dir()
    module_obj = entry.get("module_obj")
    module_file = getattr(module_obj, "__file__", None) if module_obj else None
    if module_file and not module_file.startswith("<"):
        params_json_path = os.path.splitext(module_file)[0] + ".params.json"
    else:
        params_json_path = os.path.join(strategy_dir, f"{key}.params.json")
    try:
        with open(params_json_path, "w", encoding="utf-8") as f:
            json.dump(validated, f, indent=2)
    except Exception as e:
        self.log_message(f"Error guardando .params.json para {key}: {e}")
        return

    # Reload strategy entry so params_values are updated in registry
    self._load_strategy_entry(entry)

    # Show confirmation in the params panel
    msg_escaped = json.dumps("Parámetros guardados. Se aplicarán en el próximo ciclo.")
    self.chart.run_script(f"""
        ;(function() {{
            if (window.setParamsMessage) {{
                window.setParamsMessage({msg_escaped});
            }}
        }})();
    """)
```

**Note on `_load_strategy_entry` after save**: This call reloads the module via `importlib.reload`. It updates `entry["module_obj"]`, `entry["timeframe_value"]`, `entry["magic_number"]`. It does NOT currently update `entry["params_schema"]` or `entry["params_values"]` — those fields will be populated by Alex's TASK-044 work. Felix must be aware that after the save, `entry["params_values"]` may not reflect the new file until Alex's changes are in place. The confirmation message is shown regardless, since the `.params.json` write succeeded. This is acceptable for v1.

---

## Invariant Checklist

- [x] No `chart.run_script()` from bot-loop or quote thread — all new `chart.run_script()` calls are inside `_on_strategy_params_open` and `_on_strategy_params_save`, both called from callback-loop via `on_side_panel_event`. Pattern is identical to `_on_strategy_builder_open` and `_on_strategy_builder_save` (confirmed no queue indirection needed).
- [x] DOM elements use idempotency guard before creation — `openParamsPanel` calls `document.getElementById("tv-params-overlay"); if (existing) existing.remove();` before creating a new overlay. `renderBuilderButtons` forEach uses `row.querySelector(".tv-params-btn")` guard. `_build_strategy_builder_ui` uses `if (document.getElementById("tv-builder-form-view")) return;` at entry.
- [x] No new `config.*` accesses — new code reads only from `entry` dict and `self._get_strategy_dir()`. No new `getattr(config, ...)` calls.
- [x] No new `self.*` variables — no `__init__` changes required.
- [x] Strategy registry writes only from main/callback thread — `_on_strategy_params_save` calls `_load_strategy_entry(entry)` which modifies the existing entry dict in-place. It does NOT add or remove registry keys. This matches the pattern in `_on_strategy_builder_save`. The `bot_loop` reads entry dicts in-place but does not hold a reference that conflicts with in-place updates of scalar fields.
- [x] New JS→Python action strings are unique — `"strategy_params_open"` and `"strategy_params_save"` do not appear anywhere in `gui_charts.py` (grep confirmed). No collision with any existing `on_side_panel_event` branch.
- [x] Existing "Editar" button flow unchanged — the `renderBuilderButtons` forEach restructuring preserves the exact `editBtn` logic; only the early `return` on `!has_config` is moved into an `if` guard around the `editBtn` block. The Builder open/save flow is not touched.
- [x] `_get_strategy_payload()` change is backward-compatible — `has_params: false` is the default for all strategies without `PARAMS`. `renderBuilderButtons` guards on `strategy.has_params` being truthy.

---

## Sequencing Note for Felix

1. Implement `_get_strategy_payload()` change (add `has_params`) first — this is pure Python, lowest risk.
2. Implement the two new Python methods (`_on_strategy_params_open`, `_on_strategy_params_save`) — no JS dependency.
3. Add the two new `on_side_panel_event` branches — routes to the new methods.
4. Rewrite `renderBuilderButtons` forEach in `_build_strategy_builder_ui` — structural JS change, must be done carefully. Verify the existing early-return removal does not change `editBtn` behavior.
5. Add `openParamsPanel`, `closeParamsPanel`, `setParamsMessage` JS functions and CSS to `_build_strategy_builder_ui` — new JS, lowest collision risk since it is all new identifiers.
6. Add `.tv-params-btn` CSS styling.

**Dependency on Alex (TASK-044)**: Felix can implement all of the above before Alex's backend work is merged. The `has_params` field will evaluate to `False` for all strategies until Alex's changes populate `entry["params_schema"]`. This means the "Params" button will not appear until TASK-044 is deployed — which is the correct safe behavior. No mock data or stubs are needed.
