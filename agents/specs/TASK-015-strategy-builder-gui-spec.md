# GUI Change Spec: Strategy Builder UI

**By**: Grace
**Date**: 2026-04-05
**Task**: TASK-015
**Status**: ready

---

## Summary

This change adds a visual Strategy Builder inside the existing "Estrategias" tab (`#tv-strategy-panel`). The Builder is a multi-section form that lets users define a strategy (name, timeframe, indicators, BUY/SELL condition trees) and save it — triggering Python-side file generation and immediate strategy registration, with no restart required. The change is safe to implement now: Daniel's data model (TASK-014a/b/c) is fully settled, the Builder reuses the existing `on_side_panel_event` dispatch path (no new pywebview surface), and all JS-to-Python data crosses the boundary via `json.dumps` + `encodeURIComponent` payload. The only methods that touch existing code are `_get_strategy_payload`, `_render_strategy_panel`, `setup_side_panel`, and `on_side_panel_event` — all small, targeted additions. All new Builder logic lives in new methods. The file is currently **5,876 lines**.

---

## Affected Methods

| Method | File location (approx line) | Change type | Threading context |
|--------|---------------------------|-------------|-------------------|
| `_get_strategy_payload` | ~647 | modify — add `has_config` field | main (called at setup) / callback thread (called from `_render_strategy_panel`) |
| `_render_strategy_panel` | ~1413 | modify — add `renderBuilderButtons` call | callback thread (via `on_side_panel_event`) |
| `_build_strategy_builder_ui` | ~1437 (new, after `_sync_strategy_status_ui`) | new | main thread (called once from `setup_side_panel`) |
| `setup_side_panel` | ~2846 | modify — add one call | main thread |
| `on_side_panel_event` | ~3945 | modify — add 3 new action branches | callback thread |
| `_on_strategy_builder_new` | ~3982 (new, after `_toggle_strategy_run`) | new | callback thread |
| `_on_strategy_builder_open` | ~3992 (new, after `_on_strategy_builder_new`) | new | callback thread |
| `_on_strategy_builder_save` | ~4010 (new, after `_on_strategy_builder_open`) | new | callback thread |

---

## New Instance Variables (if any)

None. Builder state (is_new flag, current magic_number, condition trees, indicator list) is maintained entirely in JavaScript as `window._strategyBuilderState`. Python instance state is not needed because each Builder action is a complete, self-contained request-response cycle through `on_side_panel_event`.

---

## Threading Analysis

All three new Python methods (`_on_strategy_builder_new`, `_on_strategy_builder_open`, `_on_strategy_builder_save`) are called from `on_side_panel_event`, which is dispatched by `_callback_loop` via `parse_event_message`. The callback thread is the established safe context for `chart.run_script()` calls. All three methods may call `chart.run_script()` directly.

`_build_strategy_builder_ui` is called once from `setup_side_panel`, which runs in the main thread — also safe for `chart.run_script()`.

`_on_strategy_builder_save` calls `builder.generate_strategy_file()` which does synchronous file I/O. This blocks the callback thread briefly (one file write at user-save frequency) — acceptable. The bot-loop thread is independent and not affected.

**No `chart.run_script()` call from bot-loop or quote thread.**

---

## JavaScript Interaction Points

### 1. `strategy_builder_new` — open empty Builder form

- **Pattern**: JS → Python → JS
- **Trigger**: User clicks "Nueva estrategia" button
- **JS → Python data**: No payload. Action string only: `handler + "_~_strategy_builder_new"`
- **Python → JS response**: `chart.run_script()` calls `window.openStrategyBuilder(config)` where `config` is a JSON payload containing `is_new: true`, a freshly generated `magic_number`, the handler string, and an empty indicator/condition skeleton.
- **Handler registration**: Uses existing `self.chart.win.handlers["side_panel_evt"]` = `on_side_panel_event`
- **Brace budget**: 1 level in `_on_strategy_builder_new` (outer IIFE only; data passed via `json.dumps` + `const payload = {payload}`)
- **Constraints**: Magic number generated in Python (not JS) to prevent collisions with existing registry entries.

### 2. `strategy_builder_open` — open Builder pre-populated for edit

- **Pattern**: JS → Python → JS
- **Trigger**: User clicks "Editar" button on a strategy row (only rendered when `entry.has_config == true`)
- **JS → Python data**: `handler + "_~_strategy_builder_open;;;" + encodeURIComponent(strategy_key)`
- **Python → JS response**: Python reads companion `.json`, calls `chart.run_script()` with `window.openStrategyBuilder(config)` where `config` is the full `StrategyConfig` JSON plus `is_new: false` and the handler string.
- **Handler registration**: Same `side_panel_evt` handler.
- **Brace budget**: 1 level (IIFE; data via `json.dumps`)
- **Constraints**: If companion `.json` is missing or unreadable, Python calls `window.openStrategyBuilderError(msg)` to display an error in the Estrategias tab without opening the form.

### 3. `strategy_builder_save` — save form and generate strategy

- **Pattern**: JS → Python
- **Trigger**: User clicks "Guardar" button
- **JS → Python data**: `handler + "_~_strategy_builder_save;;;" + encodeURIComponent(json_str)` where `json_str` is the complete `StrategyConfig` JSON assembled by JS from `window._strategyBuilderState` and the form field values. The JSON conforms to Daniel's schema from TASK-014c.
- **Python → JS response**: On success: `window.closeStrategyBuilder()` (via `chart.run_script()`), then `_render_strategy_panel()` refreshes the list. On validation or generation error: `window.setBuilderError(message)` displays the error inside the Builder form.
- **Handler registration**: Same `side_panel_evt` handler.
- **Brace budget**: 1 level per response `run_script` call (IIFE)
- **Constraints**: The JSON is URL-decoded by Python before JSON-parsing. The entire `StrategyConfig` is validated in Python before calling `builder.generate_strategy_file()`. `ast.parse` in the generator provides a final safety check (see TASK-014c).

### 4. `renderBuilderButtons` — add Edit buttons to strategy rows (Python → JS)

- **Pattern**: Python → JS
- **Trigger**: Called at end of `_render_strategy_panel()` (every time strategy list updates)
- **Data crossing the boundary**: Same `payload` object used for `renderStrategyList`, extended with `has_config` per strategy entry. The `has_config` field is a boolean indicating whether a companion `.json` exists.
- **Brace budget**: 0 extra levels (call is inside existing IIFE in `_render_strategy_panel`)
- **Constraints**: `window.renderBuilderButtons` is defined in `_build_strategy_builder_ui`. If called before that method runs (impossible in practice since both run at setup time), it is guarded by `if (window.renderBuilderButtons)` check.

---

## Insertion Point Map

### 1. `_get_strategy_payload` — add `has_config` field

**Location**: Inside `_get_strategy_payload`, in the `payload.append({...})` block at ~line 670.

**What changes**: Add one key `"has_config"` to the per-entry dict. Value is `True` if the companion `.json` file exists on disk, `False` otherwise.

**What must NOT change**: All existing keys (`key`, `label`, `module`, `enabled`, `timeframe`, `magic`, `status`, `last_run`). Their values must remain identical.

**Pseudocode**:
```
# Inside the for-loop in _get_strategy_payload, at the payload.append({...}) call:

strategy_dir = self._get_strategy_dir()
strategy_name = entry["key"]
json_path = os.path.join(strategy_dir, f"strategy_{strategy_name}.json")
has_config = os.path.isfile(json_path)

payload.append({
    # ... all existing keys unchanged ...
    "has_config": has_config,
})
```

---

### 2. `_render_strategy_panel` — add `renderBuilderButtons` call

**Location**: Inside the existing `chart.run_script(f'''...''')` block in `_render_strategy_panel`, inside the IIFE, after the `window.renderStrategyList(payload)` call.

**What changes**: Add two lines after the existing `if (window.renderStrategyList)` block:
```js
if (window.renderBuilderButtons) {
    window.renderBuilderButtons(payload);
}
```

**What must NOT change**: The existing `if (window.renderStrategyList)` block and the surrounding IIFE. The `payload` variable is already defined at the top of the IIFE — `renderBuilderButtons` receives the same object.

**Pseudocode** (Python side, inside the f-string):
```
# Current:
;(function() {{
    const payload = {payload};
    if (window.renderStrategyList) {{
        window.renderStrategyList(payload);
    }}
}})();

# After change:
;(function() {{
    const payload = {payload};
    if (window.renderStrategyList) {{
        window.renderStrategyList(payload);
    }}
    if (window.renderBuilderButtons) {{
        window.renderBuilderButtons(payload);
    }}
}})();
```

---

### 3. `setup_side_panel` — call `_build_strategy_builder_ui`

**Location**: After line ~2855 (`self._render_strategy_panel()`), before the method ends.

**What changes**: Add one line.

**What must NOT change**: All existing calls in `setup_side_panel` (`self.chart.win.handlers` assignment, `_refresh_object_tree_items`, `_build_side_panel`, `_render_strategy_panel`).

**Pseudocode**:
```
def setup_side_panel(self):
    self.side_panel_handler = 'side_panel_evt'
    self.chart.win.handlers[self.side_panel_handler] = self.on_side_panel_event
    self._refresh_object_tree_items(render=False)
    items = self.object_tree_items
    self._build_side_panel(items)
    self._render_strategy_panel()
    self._build_strategy_builder_ui()   # ← ADD THIS LINE
```

---

### 4. New method `_build_strategy_builder_ui`

**Location**: After `_sync_strategy_status_ui` at ~line 1451, before `_apply_strategy_processing_with_module` at ~line 1452.

**What changes**: New method added. Injects: (a) CSS for builder elements via a `<style>` tag; (b) "Nueva estrategia" button appended to `#tv-strategy-panel`; (c) hidden `#tv-builder-form-view` div with the full form DOM; (d) JS functions `window.openStrategyBuilder`, `window.closeStrategyBuilder`, `window.openStrategyBuilderError`, `window.setBuilderError`, `window.renderBuilderButtons`, and recursive condition-tree helpers.

**What must NOT change**: Nothing outside this method changes.

**Idempotency**: JS block begins with `if (document.getElementById("tv-builder-form-view")) return;` — safe to call multiple times (though only called once in practice).

**Brace budget**: 3 levels of nesting:
- Level 1: outer IIFE `(function() {{ ... }})();`
- Level 2: function body literals (e.g. `window.openStrategyBuilder = (config) => {{ ... }}`)
- Level 3: nested object/array literals within function bodies, always passed via `json.dumps` or constructed inline with `{{ }}` escaping

**Pseudocode** (structure of the injected JS, not verbatim):
```js
;(function() {{
    if (document.getElementById("tv-builder-form-view")) return;

    // --- CSS injection ---
    const style = document.createElement("style");
    style.textContent = `
        #tv-builder-form-view {{ display: none; ... }}
        .tv-builder-section {{ ... }}
        .tv-builder-indicator-row {{ ... }}
        .tv-builder-condition-group {{ ... }}
        .tv-builder-condition-leaf {{ ... }}
        .tv-builder-new-btn {{ ... }}
        .tv-builder-edit-btn {{ ... }}
        /* show/hide logic for builder mode */
        #tv-strategy-panel.builder-mode > :not(#tv-builder-form-view) {{ display: none !important; }}
        #tv-strategy-panel.builder-mode > #tv-builder-form-view {{ display: flex; }}
    `;
    document.head.appendChild(style);

    // --- "Nueva estrategia" button ---
    const strategyPanel = document.getElementById("tv-strategy-panel");
    if (!strategyPanel) return;
    const newBtn = document.createElement("button");
    newBtn.id = "tv-builder-new-btn";
    newBtn.type = "button";
    newBtn.className = "tv-builder-new-btn";
    newBtn.innerText = "Nueva estrategia";
    newBtn.addEventListener("click", () => {{
        window.callbackFunction(window._strategyBuilderState._handler + "_~_strategy_builder_new");
    }});
    strategyPanel.appendChild(newBtn);

    // --- Builder form view ---
    const formView = document.createElement("div");
    formView.id = "tv-builder-form-view";
    formView.className = "tv-builder-form";
    formView.innerHTML = `
        <div class="tv-builder-header">
            <span class="tv-builder-title" id="tv-builder-title">Nueva estrategia</span>
            <button type="button" id="tv-builder-cancel" class="tv-builder-cancel-btn">Cancelar</button>
        </div>
        <div class="tv-builder-body">
            <div class="tv-builder-section">
                <label>Nombre (id)</label>
                <input id="tv-builder-name" type="text" placeholder="mi_estrategia" />
                <label>Nombre visible</label>
                <input id="tv-builder-display-name" type="text" placeholder="Mi Estrategia" />
                <label>Temporalidad</label>
                <select id="tv-builder-timeframe">
                    <option value="M1">M1</option>
                    <option value="M5">M5</option>
                    <option value="M15">M15</option>
                    <option value="M30">M30</option>
                    <option value="H1">H1</option>
                    <option value="H4">H4</option>
                    <option value="D1">D1</option>
                </select>
            </div>
            <div class="tv-builder-section">
                <div class="tv-builder-section-title">Indicadores</div>
                <div class="tv-builder-indicator-picker">
                    <select id="tv-builder-indicator-type">
                        <option value="EMA">EMA</option>
                        <option value="RSI">RSI</option>
                        <option value="BB">Bollinger Bands</option>
                        <option value="DONCHIAN">Donchian Channel</option>
                        <option value="ATR">ATR</option>
                        <option value="VWAP">VWAP</option>
                        <option value="VOLUME_RATIO">Volume Ratio</option>
                        <option value="SMA">SMA</option>
                        <option value="HMA">HMA (pre-computed)</option>
                        <option value="SUPERTREND">Supertrend (pre-computed)</option>
                        <option value="TCI">TCI (pre-computed)</option>
                    </select>
                    <button type="button" id="tv-builder-add-indicator">Añadir</button>
                </div>
                <div id="tv-builder-indicator-list" class="tv-builder-indicator-list"></div>
            </div>
            <div class="tv-builder-section">
                <div class="tv-builder-section-title">Condición de Compra</div>
                <div id="tv-builder-buy-tree" class="tv-builder-tree"></div>
            </div>
            <div class="tv-builder-section">
                <div class="tv-builder-section-title">Condición de Venta</div>
                <div id="tv-builder-sell-tree" class="tv-builder-tree"></div>
            </div>
        </div>
        <div class="tv-builder-footer">
            <div id="tv-builder-error" class="tv-builder-error" style="display:none"></div>
            <button type="button" id="tv-builder-save" class="tv-builder-save-btn">Guardar</button>
        </div>
    `;
    strategyPanel.appendChild(formView);

    // --- Global builder state ---
    window._strategyBuilderState = {{
        is_new: true,
        magic_number: 0,
        editing_key: null,
        buy_tree: null,
        sell_tree: null,
        indicators: [],
        _handler: ""
    }};

    // --- openStrategyBuilder(config) ---
    // config: {{ is_new, magic_number, editing_key, name, display_name, timeframe,
    //            indicators, buy_condition, sell_condition, handler }}
    window.openStrategyBuilder = (config) => {{
        window._strategyBuilderState.is_new = !!config.is_new;
        window._strategyBuilderState.magic_number = config.magic_number || 0;
        window._strategyBuilderState.editing_key = config.editing_key || null;
        window._strategyBuilderState.indicators = config.indicators ? JSON.parse(JSON.stringify(config.indicators)) : [];
        window._strategyBuilderState.buy_tree = config.buy_condition || {{ "type": "AND", "children": [] }};
        window._strategyBuilderState.sell_tree = config.sell_condition || {{ "type": "AND", "children": [] }};
        window._strategyBuilderState._handler = config.handler || window._strategyBuilderState._handler;

        // populate meta fields
        document.getElementById("tv-builder-title").innerText = config.is_new ? "Nueva estrategia" : ("Editar: " + (config.display_name || config.name || ""));
        const nameInput = document.getElementById("tv-builder-name");
        nameInput.value = config.name || "";
        nameInput.disabled = !config.is_new;   // name locked on edit
        document.getElementById("tv-builder-display-name").value = config.display_name || "";
        document.getElementById("tv-builder-timeframe").value = config.timeframe || "M1";

        // render indicator list
        window._builderRenderIndicators();
        // render condition trees
        window._builderRenderTree("buy");
        window._builderRenderTree("sell");
        // clear any previous error
        window.setBuilderError("");

        // switch panel to builder mode
        strategyPanel.classList.add("builder-mode");
    }};

    // --- closeStrategyBuilder() ---
    window.closeStrategyBuilder = () => {{
        strategyPanel.classList.remove("builder-mode");
    }};

    // --- openStrategyBuilderError(msg) ---
    // Shows error in the strategy list view (outside the form)
    window.openStrategyBuilderError = (msg) => {{
        // Uses existing strategy status area or a temporary inline alert
        const empty = document.getElementById("tv-strategy-empty");
        if (empty) {{
            empty.style.display = "block";
            empty.innerText = "Error: " + msg;
        }}
    }};

    // --- setBuilderError(msg) ---
    window.setBuilderError = (msg) => {{
        const errEl = document.getElementById("tv-builder-error");
        if (!errEl) return;
        if (msg) {{
            errEl.innerText = msg;
            errEl.style.display = "block";
        }} else {{
            errEl.innerText = "";
            errEl.style.display = "none";
        }}
    }};

    // --- renderBuilderButtons(data) ---
    // Appends "Editar" button to each strategy row that has has_config === true
    window.renderBuilderButtons = (data) => {{
        const strategies = data.strategies || [];
        strategies.forEach((strategy) => {{
            if (!strategy.has_config) return;
            const row = document.querySelector(`.tv-strategy-item[data-key="${{strategy.key}}"]`);
            if (!row) return;
            if (row.querySelector(".tv-builder-edit-btn")) return; // idempotency
            const editBtn = document.createElement("button");
            editBtn.type = "button";
            editBtn.className = "tv-builder-edit-btn";
            editBtn.innerText = "Editar";
            editBtn.addEventListener("click", (e) => {{
                e.stopPropagation();
                const handler = (data && data.handler) ? data.handler : "";
                const key = encodeURIComponent(String(strategy.key || ""));
                window.callbackFunction(handler + "_~_strategy_builder_open;;;" + key);
            }});
            const right = row.querySelector(".tv-strategy-right");
            if (right) right.appendChild(editBtn);
        }});
    }};

    // --- Indicator list rendering ---
    // INDICATOR_PARAM_DEFS: maps indicator id to its parameter field definitions
    const INDICATOR_PARAM_DEFS = {{
        "EMA":          [{{ key: "period", label: "Período", type: "int", min: 1, default: 9 }}],
        "RSI":          [{{ key: "period", label: "Período", type: "int", min: 2, default: 14 }}],
        "BB":           [{{ key: "period", label: "Período", type: "int", min: 2, default: 20 }},
                         {{ key: "multiplier", label: "Multiplicador", type: "float", min: 0.1, default: 2.0 }}],
        "DONCHIAN":     [{{ key: "period", label: "Período", type: "int", min: 2, default: 12 }}],
        "ATR":          [{{ key: "period", label: "Período", type: "int", min: 1, default: 14 }}],
        "VWAP":         [],
        "VOLUME_RATIO": [{{ key: "lookback", label: "Lookback", type: "int", min: 2, default: 30 }}],
        "SMA":          [{{ key: "period", label: "Período", type: "int", min: 1, default: 20 }}],
        "HMA":          [],
        "SUPERTREND":   [],
        "TCI":          []
    }};

    // INDICATOR_COLUMNS_FN: given an indicator config, returns the columns it produces
    // These must match TASK-014a exactly.
    window._indicatorColumns = (ind) => {{
        const p = ind.params || {{}};
        switch (ind.id) {{
            case "EMA":          return [`ema_${{p.period}}`];
            case "RSI":          return [`rsi_${{p.period}}`];
            case "BB":           return [`bb_basis_${{p.period}}`, `bb_upper_${{p.period}}`, `bb_lower_${{p.period}}`, `bb_width_pct_${{p.period}}`];
            case "DONCHIAN":     return [`donchian_high_${{p.period}}`, `donchian_low_${{p.period}}`, `donchian_mid_${{p.period}}`];
            case "ATR":          return [`atr_${{p.period}}`, `atr_pct_${{p.period}}`];
            case "VWAP":         return ["vwap"];
            case "VOLUME_RATIO": return [`volume_ratio_${{p.lookback}}`];
            case "SMA":          return [`sma_${{p.period}}`];
            case "HMA":          return ["hma"];
            case "SUPERTREND":   return ["supertrend", "supertrend_dir", "supertrend_up", "supertrend_down"];
            case "TCI":          return ["tci", "tci_signal", "tci_hist"];
            default:             return [];
        }}
    }};

    // Always-available columns (no indicator needed)
    const ALWAYS_AVAILABLE_COLS = ["open", "high", "low", "close", "OHLC4", "HLC3", "HL2",
                                   "tick_volume", "average", "atr", "upper", "lower"];

    // getAvailableColumns: returns sorted list of all columns currently in _builderState
    window._builderGetColumns = () => {{
        const cols = new Set(ALWAYS_AVAILABLE_COLS);
        (window._strategyBuilderState.indicators || []).forEach((ind) => {{
            window._indicatorColumns(ind).forEach(c => cols.add(c));
        }});
        return Array.from(cols).sort();
    }};

    window._builderRenderIndicators = () => {{
        const list = document.getElementById("tv-builder-indicator-list");
        if (!list) return;
        list.innerHTML = "";
        (window._strategyBuilderState.indicators || []).forEach((ind, idx) => {{
            const row = document.createElement("div");
            row.className = "tv-builder-indicator-row";
            // label
            const label = document.createElement("span");
            label.className = "tv-builder-indicator-label";
            label.innerText = ind.id;
            row.appendChild(label);
            // param inputs
            const paramDefs = INDICATOR_PARAM_DEFS[ind.id] || [];
            paramDefs.forEach((def) => {{
                const inp = document.createElement("input");
                inp.type = "number";
                inp.min = def.min;
                inp.step = def.type === "float" ? "0.1" : "1";
                inp.value = (ind.params && ind.params[def.key] !== undefined) ? ind.params[def.key] : def.default;
                inp.title = def.label;
                inp.addEventListener("change", () => {{
                    const val = def.type === "float" ? parseFloat(inp.value) : parseInt(inp.value, 10);
                    ind.params[def.key] = isNaN(val) ? def.default : val;
                    // update columns field
                    ind.columns = window._indicatorColumns(ind);
                    // re-render trees to refresh column dropdowns
                    window._builderRenderTree("buy");
                    window._builderRenderTree("sell");
                }});
                row.appendChild(inp);
            }});
            // remove button
            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.innerText = "✕";
            removeBtn.addEventListener("click", () => {{
                window._strategyBuilderState.indicators.splice(idx, 1);
                window._builderRenderIndicators();
                window._builderRenderTree("buy");
                window._builderRenderTree("sell");
            }});
            row.appendChild(removeBtn);
            list.appendChild(row);
        }});
    }};

    document.getElementById("tv-builder-add-indicator").addEventListener("click", () => {{
        const typeSelect = document.getElementById("tv-builder-indicator-type");
        const id = typeSelect.value;
        const paramDefs = INDICATOR_PARAM_DEFS[id] || [];
        const params = {{}};
        paramDefs.forEach(def => {{ params[def.key] = def.default; }});
        const preComputed = ["HMA", "SUPERTREND", "TCI"].includes(id);
        const newInd = {{
            id,
            params,
            columns: window._indicatorColumns({{ id, params }}),
            pre_computed: preComputed
        }};
        window._strategyBuilderState.indicators.push(newInd);
        window._builderRenderIndicators();
        window._builderRenderTree("buy");
        window._builderRenderTree("sell");
    }});

    // --- Condition Tree rendering (recursive) ---
    const OPERATORS = ["<", ">", "<=", ">=", "==", "!="];

    // _builderRenderNode: renders a ConditionNode recursively into containerEl
    // node: the ConditionNode JSON object (mutable reference)
    // containerEl: the DOM element to append into
    // depth: current nesting depth (0-based; GUI prevents adding sub-groups at depth ≥ 5)
    window._builderRenderNode = (node, containerEl, onRemove, depth) => {{
        depth = depth || 0;
        if (node.type === "condition") {{
            // Leaf node
            const row = document.createElement("div");
            row.className = "tv-builder-condition-leaf";

            const cols = window._builderGetColumns();

            const leftSel = document.createElement("select");
            leftSel.className = "tv-builder-col-sel";
            cols.forEach(c => {{
                const opt = document.createElement("option");
                opt.value = c; opt.text = c;
                if (c === node.left) opt.selected = true;
                leftSel.appendChild(opt);
            }});
            leftSel.addEventListener("change", () => {{ node.left = leftSel.value; }});

            const opSel = document.createElement("select");
            opSel.className = "tv-builder-op-sel";
            OPERATORS.forEach(op => {{
                const opt = document.createElement("option");
                opt.value = op; opt.text = op;
                if (op === node.op) opt.selected = true;
                opSel.appendChild(opt);
            }});
            opSel.addEventListener("change", () => {{ node.op = opSel.value; }});

            // right operand: could be column (string) or scalar (number)
            // Use a type toggle + two inputs (one select for columns, one number input)
            const rightTypeBtn = document.createElement("button");
            rightTypeBtn.type = "button";
            rightTypeBtn.className = "tv-builder-right-type";
            const isColumnRef = typeof node.right === "string";
            rightTypeBtn.innerText = isColumnRef ? "col" : "val";
            rightTypeBtn.title = isColumnRef ? "Cambiar a valor escalar" : "Cambiar a columna";

            const rightColSel = document.createElement("select");
            rightColSel.className = "tv-builder-col-sel";
            rightColSel.style.display = isColumnRef ? "" : "none";
            cols.forEach(c => {{
                const opt = document.createElement("option");
                opt.value = c; opt.text = c;
                if (c === node.right) opt.selected = true;
                rightColSel.appendChild(opt);
            }});
            rightColSel.addEventListener("change", () => {{ node.right = rightColSel.value; }});

            const rightNumInp = document.createElement("input");
            rightNumInp.type = "number";
            rightNumInp.step = "any";
            rightNumInp.className = "tv-builder-num-inp";
            rightNumInp.style.display = isColumnRef ? "none" : "";
            rightNumInp.value = isColumnRef ? 0 : node.right;
            rightNumInp.addEventListener("change", () => {{
                const v = parseFloat(rightNumInp.value);
                node.right = isNaN(v) ? 0 : v;
            }});

            rightTypeBtn.addEventListener("click", () => {{
                const nowCol = rightColSel.style.display !== "none";
                if (nowCol) {{
                    // switch to scalar
                    rightColSel.style.display = "none";
                    rightNumInp.style.display = "";
                    rightTypeBtn.innerText = "val";
                    node.right = parseFloat(rightNumInp.value) || 0;
                }} else {{
                    // switch to column
                    rightNumInp.style.display = "none";
                    rightColSel.style.display = "";
                    rightTypeBtn.innerText = "col";
                    node.right = rightColSel.value || cols[0] || "close";
                }}
            }});

            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "tv-builder-remove-btn";
            removeBtn.innerText = "✕";
            removeBtn.addEventListener("click", () => {{ if (onRemove) onRemove(); }});

            row.appendChild(leftSel);
            row.appendChild(opSel);
            row.appendChild(rightTypeBtn);
            row.appendChild(rightColSel);
            row.appendChild(rightNumInp);
            row.appendChild(removeBtn);
            containerEl.appendChild(row);

        }} else if (node.type === "AND" || node.type === "OR") {{
            // Group node
            const group = document.createElement("div");
            group.className = "tv-builder-condition-group";
            group.setAttribute("data-depth", depth);

            const groupHeader = document.createElement("div");
            groupHeader.className = "tv-builder-group-header";

            const typeToggle = document.createElement("button");
            typeToggle.type = "button";
            typeToggle.className = "tv-builder-group-type";
            typeToggle.innerText = node.type;
            typeToggle.addEventListener("click", () => {{
                node.type = node.type === "AND" ? "OR" : "AND";
                typeToggle.innerText = node.type;
            }});

            const addCondBtn = document.createElement("button");
            addCondBtn.type = "button";
            addCondBtn.className = "tv-builder-add-cond-btn";
            addCondBtn.innerText = "+ Condición";
            addCondBtn.addEventListener("click", () => {{
                const newLeaf = {{ type: "condition", left: "close", op: ">", right: 0 }};
                node.children.push(newLeaf);
                renderChildren();
            }});

            const addGroupBtn = document.createElement("button");
            addGroupBtn.type = "button";
            addGroupBtn.className = "tv-builder-add-group-btn";
            addGroupBtn.innerText = "+ Grupo";
            addGroupBtn.disabled = depth >= 4;  // max depth = 5 levels (0-4)
            addGroupBtn.addEventListener("click", () => {{
                if (depth >= 4) return;
                const newGroup = {{ type: "AND", children: [] }};
                node.children.push(newGroup);
                renderChildren();
            }});

            const removeGroupBtn = document.createElement("button");
            removeGroupBtn.type = "button";
            removeGroupBtn.className = "tv-builder-remove-btn";
            removeGroupBtn.innerText = "✕";
            removeGroupBtn.addEventListener("click", () => {{ if (onRemove) onRemove(); }});

            groupHeader.appendChild(typeToggle);
            groupHeader.appendChild(addCondBtn);
            if (depth > 0) {{
                groupHeader.appendChild(addGroupBtn);
                groupHeader.appendChild(removeGroupBtn);
            }} else {{
                groupHeader.appendChild(addGroupBtn);
            }}
            group.appendChild(groupHeader);

            const childContainer = document.createElement("div");
            childContainer.className = "tv-builder-group-children";
            group.appendChild(childContainer);

            const renderChildren = () => {{
                childContainer.innerHTML = "";
                node.children.forEach((child, i) => {{
                    window._builderRenderNode(child, childContainer, () => {{
                        node.children.splice(i, 1);
                        renderChildren();
                    }}, depth + 1);
                }});
            }};
            renderChildren();

            containerEl.appendChild(group);
        }}
    }};

    window._builderRenderTree = (side) => {{
        const containerId = side === "buy" ? "tv-builder-buy-tree" : "tv-builder-sell-tree";
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = "";
        const tree = side === "buy" ? window._strategyBuilderState.buy_tree : window._strategyBuilderState.sell_tree;
        if (!tree) return;
        window._builderRenderNode(tree, container, null, 0);
    }};

    // --- Cancel button ---
    document.getElementById("tv-builder-cancel").addEventListener("click", () => {{
        window.closeStrategyBuilder();
    }});

    // --- Save button ---
    document.getElementById("tv-builder-save").addEventListener("click", () => {{
        window.setBuilderError("");
        const state = window._strategyBuilderState;
        const name = (document.getElementById("tv-builder-name").value || "").trim();
        const displayName = (document.getElementById("tv-builder-display-name").value || "").trim();
        const timeframe = document.getElementById("tv-builder-timeframe").value;

        if (!name) {{ window.setBuilderError("El nombre (id) es obligatorio."); return; }}
        if (!/^[a-z][a-z0-9_]*$/.test(name)) {{ window.setBuilderError("El nombre solo puede tener letras minúsculas, números y guión bajo, y debe empezar con letra."); return; }}
        if (!displayName) {{ window.setBuilderError("El nombre visible es obligatorio."); return; }}

        const buyTree = state.buy_tree;
        const sellTree = state.sell_tree;
        if (!buyTree || !buyTree.children || buyTree.children.length === 0) {{
            window.setBuilderError("La condición de compra no puede estar vacía.");
            return;
        }}
        if (!sellTree || !sellTree.children || sellTree.children.length === 0) {{
            window.setBuilderError("La condición de venta no puede estar vacía.");
            return;
        }}

        const config = {{
            schema_version: 1,
            name: name,
            display_name: displayName,
            description: "",
            timeframe: timeframe,
            magic_number: state.magic_number,
            indicators: JSON.parse(JSON.stringify(state.indicators)),
            buy_condition: JSON.parse(JSON.stringify(buyTree)),
            sell_condition: JSON.parse(JSON.stringify(sellTree)),
            _is_new: state.is_new,
            _editing_key: state.editing_key
        }};

        const json = JSON.stringify(config);
        window.callbackFunction(state._handler + "_~_strategy_builder_save;;;" + encodeURIComponent(json));
    }});

}})();
```

---

### 5. `on_side_panel_event` — add 3 new action branches

**Location**: Inside `on_side_panel_event` at ~line 3945, after the existing `if action == "strategy_toggle"` block (~line 3978-3980) and before the method ends.

**What changes**: Add 3 new `if` blocks.

**What must NOT change**: All existing action branches (toggle, strategy_data_scope, strategy_data_scope_all_actives, strategy_select, strategy_enable_toggle, strategy_add, strategy_drop, strategy_toggle).

**Pseudocode**:
```
def on_side_panel_event(self, action, *args):
    # ... all existing branches unchanged ...

    if action == "strategy_builder_new":
        self._on_strategy_builder_new()
        return
    if action == "strategy_builder_open" and args:
        key = unquote(args[0]) if len(args) > 0 else ""
        self._on_strategy_builder_open(key)
        return
    if action == "strategy_builder_save" and args:
        json_str = unquote(args[0]) if len(args) > 0 else ""
        self._on_strategy_builder_save(json_str)
        return
```

---

### 6. New method `_on_strategy_builder_new`

**Location**: After `_toggle_strategy_run` at ~line 3993, before whatever follows.

**What changes**: New method. Generates a fresh magic number (random 5-digit int not in current registry), builds an open-builder payload, calls `chart.run_script()` with `window.openStrategyBuilder(config)`.

**What must NOT change**: Nothing external changes.

**Pseudocode**:
```
def _on_strategy_builder_new(self):
    # Generate magic number not already in use
    import random
    used_magics = {int(e.get("magic_number") or 0) for e in self.strategy_registry.values()}
    while True:
        magic = random.randint(10000, 99999)
        if magic not in used_magics:
            break

    payload = json.dumps({
        "is_new": True,
        "magic_number": magic,
        "editing_key": None,
        "name": "",
        "display_name": "",
        "timeframe": "M1",
        "indicators": [],
        "buy_condition": {"type": "AND", "children": []},
        "sell_condition": {"type": "AND", "children": []},
        "handler": self.side_panel_handler,
    })
    self.chart.run_script(f'''
        ;(function() {{
            const payload = {payload};
            if (window.openStrategyBuilder) {{
                window.openStrategyBuilder(payload);
            }}
        }})();
    ''')
```

---

### 7. New method `_on_strategy_builder_open`

**Location**: After `_on_strategy_builder_new`.

**What changes**: New method. Reads companion `.json` for a strategy, sends it to JS to pre-populate the builder form.

**What must NOT change**: Nothing external changes. Registry is read-only here.

**Pseudocode**:
```
def _on_strategy_builder_open(self, key: str):
    key = (key or "").strip()
    entry = self._get_strategy_entry(key)
    if not entry:
        self.chart.run_script(f'''
            ;(function() {{
                if (window.openStrategyBuilderError) {{
                    window.openStrategyBuilderError("Estrategia no encontrada: {key}");
                }}
            }})();
        ''')
        return

    strategy_dir = self._get_strategy_dir()
    # Key is the machine name (same as strategy file stem after "strategy_")
    # However, entries loaded from disk use the module_ref stem to derive key,
    # so the json filename uses the key directly.
    json_path = os.path.join(strategy_dir, f"strategy_{key}.json")
    if not os.path.isfile(json_path):
        self.chart.run_script(f'''
            ;(function() {{
                if (window.openStrategyBuilderError) {{
                    window.openStrategyBuilderError("No se encontró la configuración editable para esta estrategia.");
                }}
            }})();
        ''')
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        err_escaped = str(e).replace('"', '\\"').replace("'", "\\'")
        self.chart.run_script(f'''
            ;(function() {{
                if (window.openStrategyBuilderError) {{
                    window.openStrategyBuilderError("Error al leer configuración: {err_escaped}");
                }}
            }})();
        ''')
        return

    config["is_new"] = False
    config["editing_key"] = key
    config["handler"] = self.side_panel_handler

    payload = json.dumps(config)
    self.chart.run_script(f'''
        ;(function() {{
            const payload = {payload};
            if (window.openStrategyBuilder) {{
                window.openStrategyBuilder(payload);
            }}
        }})();
    ''')
```

---

### 8. New method `_on_strategy_builder_save`

**Location**: After `_on_strategy_builder_open`.

**What changes**: New method. Receives the save payload, validates it, calls the generator (from `strategies/builder.py` — TASK-017), registers the strategy in the registry, and refreshes the UI.

**What must NOT change**: Nothing external changes during the success path except: `self.strategy_registry` (modified to add/update strategy entry), `config.ACTIVE_STRATEGIES` (updated to include new strategy), and the strategy files on disk.

**Threading**: Runs in the callback thread. File I/O is synchronous and acceptable here.

**Pseudocode**:
```
def _on_strategy_builder_save(self, json_str: str):
    json_str = (json_str or "").strip()
    if not json_str:
        self._show_builder_error("Payload vacío.")
        return

    try:
        config_data = json.loads(json_str)
    except Exception as e:
        self._show_builder_error(f"JSON inválido: {e}")
        return

    # --- Basic validation ---
    name = (config_data.get("name") or "").strip()
    display_name = (config_data.get("display_name") or "").strip()
    timeframe = (config_data.get("timeframe") or "").strip()
    magic_number = config_data.get("magic_number")
    is_new = bool(config_data.get("_is_new", True))
    editing_key = config_data.get("_editing_key") or None

    import re as _re
    if not name or not _re.match(r'^[a-z][a-z0-9_]*$', name):
        self._show_builder_error("Nombre inválido. Solo letras minúsculas, números y guión bajo.")
        return
    if not display_name:
        self._show_builder_error("El nombre visible es obligatorio.")
        return
    valid_timeframes = {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}
    if timeframe not in valid_timeframes:
        self._show_builder_error(f"Temporalidad inválida: {timeframe}")
        return
    if not isinstance(magic_number, int) or not (10000 <= magic_number <= 99999):
        self._show_builder_error("Magic number inválido.")
        return

    # --- Name collision check for new strategies ---
    if is_new and name in self.strategy_registry:
        self._show_builder_error(f"Ya existe una estrategia con el nombre '{name}'.")
        return

    # --- Strip internal fields before passing to generator ---
    generator_config = {k: v for k, v in config_data.items() if not k.startswith("_")}

    # --- Call generator (TASK-017 implementation) ---
    strategies_dir = self._get_strategy_dir()
    try:
        import importlib
        strategy_builder = importlib.import_module("strategies.builder")
        py_path = strategy_builder.generate_strategy_file(
            generator_config,
            strategies_dir,
            is_new=is_new
        )
    except ImportError:
        self._show_builder_error("El generador de estrategias aún no está implementado (TASK-017).")
        return
    except Exception as e:
        self._show_builder_error(f"Error al generar estrategia: {e}")
        return

    # --- Register strategy in registry ---
    module_ref = str(py_path)
    if name not in self.strategy_registry:
        self._register_strategy(name, display_name, module_ref)
    else:
        # Edit: update label and module_ref, preserve magic_number
        entry = self.strategy_registry[name]
        entry["label"] = display_name
        entry["module"] = module_ref

    entry = self.strategy_registry.get(name)
    if entry:
        self._load_strategy_entry(entry)
        entry["enabled"] = True
    config.ACTIVE_STRATEGIES = [e["key"] for e in self.strategy_registry.values() if e.get("enabled")]

    # --- Close builder and refresh UI ---
    self.chart.run_script('''
        ;(function() {
            if (window.closeStrategyBuilder) {
                window.closeStrategyBuilder();
            }
        })();
    ''')
    self._render_strategy_panel()

def _show_builder_error(self, message: str):
    # Helper: sends error to the builder form's error display
    msg_escaped = json.dumps(message)
    self.chart.run_script(f'''
        ;(function() {{
            if (window.setBuilderError) {{
                window.setBuilderError({msg_escaped});
            }}
        }})();
    ''')
```

Note: `_show_builder_error` is an additional small helper method, placed immediately after `_on_strategy_builder_save`. It has 1 brace level.

---

## Invariant Checklist

- [x] No `chart.run_script()` from non-main-thread context — all new `chart.run_script()` calls are in methods dispatched through the callback thread (`on_side_panel_event`) or in `setup_side_panel` (main thread), both safe contexts.
- [x] DOM elements use `getElementById` guard before creation — `_build_strategy_builder_ui` JS begins with `if (document.getElementById("tv-builder-form-view")) return;`
- [x] New config accesses use `getattr(config, "KEY", default)` pattern — no new config accesses added; `_get_strategy_dir()` already uses `getattr(config, "STRATEGY_DIR", "strategies")`.
- [x] New `self.*` variables initialized in `__init__` before first use — no new instance variables.
- [x] Strategy registry reads from bot-loop are read-only (no writes from bot-loop during this change) — `_on_strategy_builder_save` writes to the registry but runs in the callback thread, not the bot-loop thread. Bot-loop reads only `_get_enabled_strategy_entries()` which takes a list snapshot. The write in `_on_strategy_builder_save` is a dict key assignment; Python's GIL makes this safe relative to the bot-loop's snapshot read.
- [x] Any new JS→Python handler name is unique — no new handler names registered; all new actions dispatch through the existing `side_panel_evt` handler.

---

## Additional Notes for Felix

### CSS class names introduced
`tv-builder-form`, `tv-builder-header`, `tv-builder-title`, `tv-builder-cancel-btn`, `tv-builder-body`, `tv-builder-section`, `tv-builder-section-title`, `tv-builder-indicator-picker`, `tv-builder-indicator-list`, `tv-builder-indicator-row`, `tv-builder-indicator-label`, `tv-builder-tree`, `tv-builder-condition-group`, `tv-builder-group-header`, `tv-builder-group-type`, `tv-builder-group-children`, `tv-builder-add-cond-btn`, `tv-builder-add-group-btn`, `tv-builder-condition-leaf`, `tv-builder-col-sel`, `tv-builder-op-sel`, `tv-builder-right-type`, `tv-builder-num-inp`, `tv-builder-remove-btn`, `tv-builder-footer`, `tv-builder-error`, `tv-builder-save-btn`, `tv-builder-new-btn`, `tv-builder-edit-btn`, `builder-mode` (on `#tv-strategy-panel`).

None of these class names conflict with existing class names in the codebase (confirmed by the naming prefix `tv-builder-`).

### CSS show/hide mechanism
The `builder-mode` CSS class on `#tv-strategy-panel` controls visibility:
```css
#tv-strategy-panel.builder-mode > :not(#tv-builder-form-view) { display: none !important; }
#tv-strategy-panel.builder-mode > #tv-builder-form-view { display: flex; flex-direction: column; }
```
This is injected via a `<style>` tag in `_build_strategy_builder_ui`.

### `has_config` performance note
`os.path.isfile()` is called once per strategy entry on every `_render_strategy_panel()` call. With the expected number of strategies (< 20), this is a negligible disk stat call.

### Generator import pattern
`_on_strategy_builder_save` uses `importlib.import_module("strategies.builder")` (dynamic import) so the save gracefully degrades with an error message if TASK-017 has not been implemented yet. Felix must implement the import exactly as shown.

### Condition tree depth limit
The GUI disables "Añadir grupo" at depth ≥ 4 (0-based), enforcing a maximum of 5 nesting levels. This matches Daniel's recommendation in TASK-014b (EC-4).

### VWAP + D1 warning
When the user selects VWAP as an indicator AND the timeframe selector shows D1, the JS should add a warning. Felix should implement this as an inline warning label that appears in the Indicators section when this combination is detected. No Python involvement needed — pure JS check in `_builderRenderIndicators`.

### Edit flow: `_editing_key` vs `name`
On edit, `_editing_key` holds the registry key from before the save. If the user changes the strategy `name` during an edit, `_on_strategy_builder_save` must detect this and treat it as a create (new file), not overwrite. For v1, the simplest behavior: disable the `name` input on edit (already specified above: `nameInput.disabled = !config.is_new`), so the name never changes during an edit.

### Backtest tab (future)
This change adds one tab-visible element ("Nueva estrategia" button) and one tab-hidden view (`#tv-builder-form-view`), both inside the existing "Estrategias" tab. No assumptions are made about the number of tabs in `legacyPanel`. A future "Backtest" tab can be added to `legacyTabs` without touching any of this code.
