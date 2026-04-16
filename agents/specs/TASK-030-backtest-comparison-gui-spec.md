# GUI Change Spec: Backtest — panel de comparación de estrategias

**By**: Grace
**Date**: 2026-04-11
**Task**: TASK-030
**Status**: ready

---

## Backend Summary

Daniel's TASK-029 spec defines `run_backtest_comparison(request: dict) -> dict`. Key facts Felix needs:

- **New public function**: `run_backtest_comparison` in `backtesting/runtime.py` (parallel to `run_backtest`)
- **Input**: `symbol`, `start_date`, `end_date`, `initial_balance`, plus a `strategies: list[dict]` array (each with `strategy_key`, `strategy_label`, `module`, optional `timeframe_value`)
- **Output**: top-level `status` (`"success"` | `"partial"` | `"error"`), `error`, `symbol`, `start_date`, `end_date`, `initial_balance`, and `strategies: list[StrategyComparisonEntry]`
- **Each entry**: `status`, `error`, `strategy_key`, `strategy_label`, `timeframe`, `initial_balance`, `final_balance`, `total_profit`, `total_return_pct`, `closed_trades`, `winning_trades`, `losing_trades`, `win_rate`, `max_drawdown` — **no** `trades` or `equity_curve` arrays
- **Partial failure**: if one strategy errors the others still run; top-level `status` becomes `"partial"`
- **Module objects** must be resolved by Python before building the request (same as `_on_backtest_run` does today with `entry.get("module_obj")`)
- Import path: `from backtesting.runtime import run_backtest_comparison` (alongside the existing `run_backtest` import)

---

## Summary

This spec adds a "Comparar" mode to the existing Backtest tab. The panel acquires a mode toggle (Individual / Comparar) above the strategy field. In compare mode, the single `<select>` is hidden and replaced by a scrollable checkbox list. A separate "Comparar estrategias" button fires `backtest_compare` action to Python. Python adds three new methods (`_on_backtest_compare`, `_run_backtest_comparison_worker`, `_render_backtest_comparison_panel`) and a new `backtest_compare` branch in `on_side_panel_event`. Results render in a new `#tv-backtest-comparison-results` div — a compact 6-column HTML table. Single-mode result sections are hidden while comparison results are visible and vice versa.

TASK-028 insertion points are in the CSS (after line ~3326), the `backtestPanel.innerHTML` (after line ~4020), inside `renderBacktestPanel` (after line ~4593), and a new `renderBacktestCharts` function (after line ~4594). TASK-030 inserts **after** all of those, with one exception: the mode toggle and checkbox list go inside `backtestPanel.innerHTML`, which modifies a region that overlaps with TASK-028's HTML addition — but only in that TASK-030's additions come **after** TASK-028's additions. Felix must apply TASK-028 first, then TASK-030.

---

## Affected Methods

| Method | File location (approx line) | Change type | Threading context |
|--------|---------------------------|-------------|-------------------|
| `__init__` | ~208 | modify (add 3 new state keys + `self.comparison_thread`) | main |
| `_get_backtest_form_state` | ~743 | modify (add `comparison_strategy_keys`) | main (called from `_get_backtest_payload`) |
| `_get_backtest_payload` | ~778 | no change required | main |
| `on_side_panel_event` | ~5229 | modify (add `backtest_compare` branch) | main |
| `_on_backtest_compare` | new, ~925 | new | main |
| `_run_backtest_comparison_worker` | new, ~960 | new | backtest-comparison-worker thread (same exception pattern as `_run_backtest_worker`) |
| `_render_backtest_comparison_panel` | new, ~985 | new | backtest-comparison-worker thread (same exception pattern) |

No changes to `_render_backtest_panel`, `_run_backtest_worker`, or `_on_backtest_run`.

---

## New Instance Variables

Add to `__init__` immediately after the `self.backtest_state` initialization block (~line where `self.backtest_state` is assigned):

```python
self.comparison_thread = None          # daemon Thread reference, mirrors self.backtest_thread
```

Add three new keys inside `self.backtest_state` initialization (or immediately after it):

```python
self.backtest_state["comparison_running"] = False
self.backtest_state["comparison_result"]  = None
self.backtest_state["comparison_error"]   = ""
```

**Invariant**: `comparison_result` is only written from `_run_backtest_comparison_worker` (the comparison-worker thread). It is read in `_render_backtest_comparison_panel` in the same thread and by `renderBacktestPanel` JS via the payload. This is the same pattern as `backtest_state["result"]` with `_run_backtest_worker`.

---

## Threading Analysis

`_on_backtest_compare` is called from `on_side_panel_event` — main thread. It spawns `self.comparison_thread` (daemon). `_run_backtest_comparison_worker` runs in that thread.

`_render_backtest_comparison_panel` is called from `_run_backtest_comparison_worker` and calls `self.chart.run_script()` directly. This follows the pre-existing exception to the callback-queue rule: both `_run_backtest_worker` and `_render_backtest_panel` already do this. The comparison render follows the identical pattern. No new threading exception is introduced.

**Confirm: No `chart.run_script()` call from bot-loop or quote thread.** The comparison-worker thread is a purpose-built daemon thread identical in structure to `self.backtest_thread`.

---

## JavaScript Interaction Points

### 1. Comparison run button (JS → Python)

- **Pattern**: JS → Python
- **Trigger**: User clicks "Comparar estrategias" button
- **Data crossing**: JSON string `{"strategy_keys": ["key1","key2",...], "symbol": "...", "preset": "...", "start_date": "...", "end_date": "...", "initial_balance": "..."}`
- **Handler registration**: Routed through existing `self.chart.win.handlers[side_panel_handler]` → `on_side_panel_event` with action `"backtest_compare"` — no new handler registration needed
- **JS event string**: `state.handler + "_~_backtest_compare;;;" + encodeURIComponent(JSON.stringify(request))`
- **Brace budget**: 1 level (same as the existing `runBtn.onclick` for single mode)
- **Constraint**: The compare button must validate that `≥ 2` checkboxes are checked before firing; if fewer, it sets an error message in the status line without calling Python

### 2. Comparison panel render (Python → JS)

- **Pattern**: Python → JS with JSON
- **Trigger**: `_render_backtest_comparison_panel` called at end of `_run_backtest_comparison_worker`
- **Data crossing**: `{"comparison_running": bool, "comparison_result": dict|null, "comparison_error": str}`
- **Called function**: `window.renderBacktestComparison(data)` — new window-level function
- **Brace budget**: 1 level (outer IIFE `{{ }}`)
- **Constraint**: The JSON payload is safe from brace issues (serialized with `json.dumps` before insertion)

### 3. Mode toggle + checkbox population (Python → JS, inside existing `renderBacktestPanel`)

- **Pattern**: Extension of existing Python → JS with JSON flow (no new boundary crossing)
- **Trigger**: `renderBacktestPanel` called (same as today, on any backtest state change)
- **What changes**: The JS inside `renderBacktestPanel` also populates `#tv-backtest-strategy-checks` with one checkbox per strategy, restores `state.backtest_mode`, and shows/hides the correct strategy selector

---

## Insertion Point Map

### 1. New CSS classes in `_inject_custom_styles`

**Location**: After the last CSS block added by TASK-028 (the `.tv-backtest-trade-loss` closing `}}`), approximately line ~3390 after TASK-028 is applied. Before the `.tv-confirm-overlay {` block.

**Tolerance**: ±5 lines

**What changes**: Insert the following CSS block (inside f-string — escape all `{` / `}` as `{{` / `}}`):

```css
.tv-backtest-mode-toggle {
    display: flex;
    gap: 4px;
    margin-bottom: 6px;
}
.tv-backtest-mode-btn {
    flex: 1;
    font-size: 11px;
    padding: 4px 0;
    background: #1e1e1e;
    color: #8f8f8f;
    border: 1px solid #333;
    border-radius: 3px;
    cursor: pointer;
}
.tv-backtest-mode-btn.active {
    background: #2962ff;
    color: #ffffff;
    border-color: #2962ff;
}
.tv-backtest-strategy-checks {
    max-height: 110px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 4px 0;
}
.tv-backtest-strategy-check-row {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: #c0c0c0;
    cursor: pointer;
}
.tv-backtest-strategy-check-row input[type="checkbox"] {
    accent-color: #2962ff;
    cursor: pointer;
}
.tv-backtest-strategy-check-row.disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
.tv-backtest-comparison-wrapper {
    overflow-x: auto;
    margin-top: 8px;
}
.tv-backtest-comparison-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 10px;
    color: #c0c0c0;
    min-width: 260px;
}
.tv-backtest-comparison-table th {
    font-size: 9px;
    color: #8f8f8f;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 4px 4px;
    background: #1a1a1a;
    position: sticky;
    top: 0;
    z-index: 1;
    border-bottom: 1px solid #2f2f2f;
    white-space: nowrap;
}
.tv-backtest-comparison-table td {
    padding: 4px 4px;
    border-bottom: 1px solid #252525;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.tv-backtest-comparison-table tr:hover td {
    background: #1f1f1f;
}
.tv-backtest-comparison-table td.cmp-win {
    color: #5cb85c;
}
.tv-backtest-comparison-table td.cmp-loss {
    color: #d9534f;
}
.tv-backtest-comparison-table td.cmp-error {
    color: #d9534f;
    font-style: italic;
}
```

**What must NOT change**: The TASK-028 CSS block above (`.tv-backtest-trade-loss`) and the `.tv-confirm-overlay` block below.

---

### 2. HTML modifications inside `backtestPanel.innerHTML`

This spec requires **two insertion points** inside the `backtestPanel.innerHTML` template string (~lines 3980–4021, shifting after TASK-028 adds content after line 4020).

#### 2a. Mode toggle + checkbox list inside the Estrategia field

**Location**: Inside the existing Estrategia field div. Currently (~line 3987–3989):
```html
<div class="tv-backtest-field">
    <label>Estrategia</label>
    <select id="tv-backtest-strategy"></select>
</div>
```

**What changes**: Extend this div to include the mode toggle before the label and a hidden checkbox container after the select:

```html
<div class="tv-backtest-field">
    <div class="tv-backtest-mode-toggle">
        <button type="button" class="tv-backtest-mode-btn active" id="tv-backtest-mode-single">Individual</button>
        <button type="button" class="tv-backtest-mode-btn" id="tv-backtest-mode-compare">Comparar</button>
    </div>
    <label>Estrategia</label>
    <select id="tv-backtest-strategy"></select>
    <div class="tv-backtest-strategy-checks" id="tv-backtest-strategy-checks" style="display:none;"></div>
</div>
```

**What must NOT change**: The other form fields (Símbolo, Timeframe, Ventana, Fecha inicio, Fecha fin, Balance inicial) are untouched.

#### 2b. Compare button in the actions section + comparison results container

**Location (compare button)**: Inside `<div class="tv-backtest-actions">` (~line 4015–4018). Currently:
```html
<div class="tv-backtest-actions">
    <button type="button" id="tv-backtest-run">Ejecutar backtest</button>
    <div class="tv-backtest-status" id="tv-backtest-status">Sin ejecución todavía.</div>
</div>
```

**What changes**: Add the compare button after the run button, hidden by default:
```html
<div class="tv-backtest-actions">
    <button type="button" id="tv-backtest-run">Ejecutar backtest</button>
    <button type="button" id="tv-backtest-compare-btn" style="display:none;">Comparar estrategias</button>
    <div class="tv-backtest-status" id="tv-backtest-status">Sin ejecución todavía.</div>
</div>
```

**Location (comparison results div)**: After the last TASK-028 section (`#tv-backtest-trades-section`), before the closing backtick of `backtestPanel.innerHTML`. Approximately line ~4046 after TASK-028 is applied (TASK-028 adds ~25 lines after the original line 4020).

**What changes**: Add the comparison results container:
```html
<div class="tv-backtest-section" id="tv-backtest-comparison-results" style="display:none;">
    <div class="tv-backtest-section-title">Comparación de estrategias</div>
    <div class="tv-backtest-comparison-wrapper">
        <table class="tv-backtest-comparison-table" id="tv-backtest-comparison-table">
            <thead>
                <tr>
                    <th>Estrategia</th>
                    <th>Ops</th>
                    <th>Win%</th>
                    <th>Max DD%</th>
                    <th>Ret%</th>
                    <th>PF</th>
                </tr>
            </thead>
            <tbody id="tv-backtest-comparison-tbody"></tbody>
        </table>
    </div>
</div>
```

**DOM element IDs introduced** (grepped, no collisions in current file):
- `tv-backtest-mode-single`
- `tv-backtest-mode-compare`
- `tv-backtest-strategy-checks`
- `tv-backtest-compare-btn`
- `tv-backtest-comparison-results`
- `tv-backtest-comparison-table`
- `tv-backtest-comparison-tbody`

**What must NOT change**: The TASK-028 new sections (`#tv-backtest-extra-cards`, `#tv-backtest-equity-section`, `#tv-backtest-drawdown-section`, `#tv-backtest-trades-section`) above. The `#tv-backtest-results` div. The original form fields.

---

### 3. Extensions to `renderBacktestPanel` JS (inside `_build_side_panel`)

**Location**: After the TASK-028 extension block (end of `renderBacktestPanel`, after the trades table code added by TASK-028), before the closing `}};` of `renderBacktestPanel`. Approximately line ~4630 after TASK-028 is applied (TASK-028 adds ~35 lines inside this function).

**Tolerance**: ±5 lines

**What changes**: Append the following logic block at the very end of `renderBacktestPanel` (still inside the function, before its closing `}};`).

This block handles:
1. Mode toggle button wiring (idempotent — only wire if not already wired, guarded by a flag on the element)
2. Checkbox list population
3. Show/hide of single vs compare widgets per current mode
4. Show/hide of the compare button vs run button
5. Hiding single-mode result sections when in compare mode

Because this code is inside the f-string, all JS `{` / `}` must be escaped as `{{` / `}}`.

**Pseudocode (Felix translates to escaped f-string JS)**:

```
// --- Mode toggle setup ---
const modeSingleBtn  = document.getElementById("tv-backtest-mode-single")
const modeCompareBtn = document.getElementById("tv-backtest-mode-compare")
const strategySel    = document.getElementById("tv-backtest-strategy")  // already declared above; reuse
const checksEl       = document.getElementById("tv-backtest-strategy-checks")
const compareBtn     = document.getElementById("tv-backtest-compare-btn")
const runBtn_ref     = document.getElementById("tv-backtest-run")  // already declared above as runBtn; reuse ref

// Restore persisted mode (default "single")
if (!state.backtest_mode) state.backtest_mode = "single"

// Helper: apply current mode to DOM visibility
const applyMode = (mode) => {
    state.backtest_mode = mode
    const isCompare = mode === "compare"
    if (modeSingleBtn)  modeSingleBtn.classList.toggle("active", !isCompare)
    if (modeCompareBtn) modeCompareBtn.classList.toggle("active", isCompare)
    if (strategySel)    strategySel.style.display  = isCompare ? "none" : ""
    if (checksEl)       checksEl.style.display      = isCompare ? "" : "none"
    if (runBtn_ref)     runBtn_ref.style.display     = isCompare ? "none" : ""
    if (compareBtn)     compareBtn.style.display     = isCompare ? "" : "none"
    // Hide single-mode result sections when in compare mode
    const singleResultIds = [
        "tv-backtest-results", "tv-backtest-extra-cards",
        "tv-backtest-equity-section", "tv-backtest-drawdown-section",
        "tv-backtest-trades-section"
    ]
    singleResultIds.forEach(id => {
        const el = document.getElementById(id)
        if (el) el.style.display = isCompare ? "none" : el._lastDisplay || ""
    })
    // Hide comparison results when in single mode
    const cmpEl = document.getElementById("tv-backtest-comparison-results")
    if (cmpEl) cmpEl.style.display = isCompare ? cmpEl._lastDisplay || "" : "none"
}

// Wire mode buttons (once — guard with dataset flag)
if (modeSingleBtn && !modeSingleBtn.dataset.modeBound) {
    modeSingleBtn.dataset.modeBound = "1"
    modeSingleBtn.addEventListener("click", () => applyMode("single"))
}
if (modeCompareBtn && !modeCompareBtn.dataset.modeBound) {
    modeCompareBtn.dataset.modeBound = "1"
    modeCompareBtn.addEventListener("click", () => applyMode("compare"))
}

// --- Populate checkbox list ---
if (checksEl) {
    // Store currently checked keys before clearing
    const checkedKeys = new Set()
    checksEl.querySelectorAll("input[type='checkbox']:checked").forEach(cb => checkedKeys.add(cb.value))

    checksEl.innerHTML = ""
    state.strategies.forEach(entry => {
        if (!entry || !entry.key) return
        const row = document.createElement("div")
        row.className = "tv-backtest-strategy-check-row" + (entry.disabled ? " disabled" : "")
        const cb = document.createElement("input")
        cb.type = "checkbox"
        cb.value = entry.key
        cb.disabled = !!entry.disabled
        cb.checked = checkedKeys.has(entry.key)
        const lbl = document.createElement("label")
        lbl.innerText = entry.label || entry.key
        row.appendChild(cb)
        row.appendChild(lbl)
        row.addEventListener("click", () => { if (!entry.disabled) cb.checked = !cb.checked })
        cb.addEventListener("click", e => e.stopPropagation())
        checksEl.appendChild(row)
    })
}

// --- Wire compare button ---
if (compareBtn && !compareBtn.dataset.compareBound) {
    compareBtn.dataset.compareBound = "1"
    compareBtn.addEventListener("click", () => {
        if (!checksEl) return
        const selectedKeys = []
        checksEl.querySelectorAll("input[type='checkbox']:checked").forEach(cb => {
            if (!cb.disabled) selectedKeys.push(cb.value)
        })
        if (selectedKeys.length < 2) {
            // Show inline error — reuse statusEl
            const statusEl = document.getElementById("tv-backtest-status")
            if (statusEl) statusEl.innerText = "Selecciona al menos 2 estrategias para comparar"
            return
        }
        if (state.comparison_running) {
            const statusEl = document.getElementById("tv-backtest-status")
            if (statusEl) statusEl.innerText = "Comparación en ejecución..."
            return
        }
        const request = {
            strategy_keys:   selectedKeys,
            symbol:          state.form.symbol || "",
            preset:          state.form.preset || "CUSTOM",
            start_date:      (document.getElementById("tv-backtest-start") || {}).value || "",
            end_date:        (document.getElementById("tv-backtest-end") || {}).value || "",
            initial_balance: (document.getElementById("tv-backtest-balance") || {}).value || "",
        }
        if (window.callbackFunction && state.handler) {
            window.callbackFunction(state.handler + "_~_backtest_compare;;;" + encodeURIComponent(JSON.stringify(request)))
        }
    })
}

// Apply current mode to keep DOM consistent on every re-render
applyMode(state.backtest_mode || "single")
```

**Note on `_lastDisplay`**: The `_lastDisplay` trick is not reliable. Felix should instead track whether the comparison result or single result is present and set display directly rather than relying on a stored previous display value. See invariant checklist.

---

### 4. New `window.renderBacktestComparison` function

**Location**: After `window.renderBacktestCharts` (added by TASK-028, approximately line ~4660 after TASK-028 is applied), before `window.tvEyeSvg = ...`.

**Tolerance**: ±5 lines

**Preferred implementation path**: Define this function in a **separate** `self.chart.run_script()` call at GUI setup time (e.g., appended at the end of `_inject_custom_styles`), so the function body is plain unescaped JS. This avoids brace explosion. If Felix chooses this path, the function lives outside the `_build_side_panel` f-string entirely.

If placed inside the `_build_side_panel` f-string, all JS `{` / `}` must be escaped as `{{` / `}}`.

**Pseudocode**:

```
window.renderBacktestComparison = (data) => {
    const cmpEl    = document.getElementById("tv-backtest-comparison-results")
    const tbody    = document.getElementById("tv-backtest-comparison-tbody")
    const statusEl = document.getElementById("tv-backtest-status")
    const errorEl  = document.getElementById("tv-backtest-error")
    if (!cmpEl || !tbody) return

    const running = !!data.comparison_running
    const err     = data.comparison_error || ""
    const result  = data.comparison_result || null

    // Update status / error display
    if (statusEl) {
        if (running) statusEl.innerText = "Comparando estrategias..."
        else if (result) statusEl.innerText = "Comparación completada"
        else statusEl.innerText = "Sin ejecución todavía."
    }
    if (errorEl) {
        errorEl.innerText = err
        errorEl.style.display = err ? "block" : "none"
    }

    // Hide all single-mode result sections
    ["tv-backtest-results", "tv-backtest-extra-cards",
     "tv-backtest-equity-section", "tv-backtest-drawdown-section",
     "tv-backtest-trades-section"].forEach(id => {
        const el = document.getElementById(id)
        if (el) el.style.display = "none"
    })

    if (!result || !Array.isArray(result.strategies) || result.strategies.length === 0) {
        cmpEl.style.display = "none"
        return
    }

    tbody.innerHTML = ""
    result.strategies.forEach(entry => {
        const tr = document.createElement("tr")
        if (entry.status === "error") {
            const td0 = document.createElement("td")
            td0.innerText = entry.strategy_label || entry.strategy_key || "?"
            const td1 = document.createElement("td")
            td1.colSpan = 5
            td1.className = "cmp-error"
            td1.innerText = "Error: " + (entry.error || "desconocido")
            tr.appendChild(td0)
            tr.appendChild(td1)
        } else {
            const retPct  = Number(entry.total_return_pct || 0)
            const pf      = Number(entry.profit_factor    || 0)
            const maxDD   = Number(entry.max_drawdown     || 0)
            const winRate = Number(entry.win_rate         || 0)
            const ops     = Number(entry.closed_trades    || 0)

            const cells = [
                {text: entry.strategy_label || entry.strategy_key || "?", cls: ""},
                {text: String(ops),                                         cls: ""},
                {text: winRate.toFixed(1) + "%",                            cls: winRate >= 50 ? "cmp-win" : "cmp-loss"},
                {text: maxDD.toFixed(2) + "%",                              cls: maxDD > 10 ? "cmp-loss" : ""},
                {text: (retPct >= 0 ? "+" : "") + retPct.toFixed(2) + "%", cls: retPct >= 0 ? "cmp-win" : "cmp-loss"},
                {text: pf > 0 ? pf.toFixed(2) : "--",                       cls: pf >= 1 ? "cmp-win" : (pf > 0 ? "cmp-loss" : "")},
            ]
            cells.forEach(c => {
                const td = document.createElement("td")
                td.innerText = c.text
                if (c.cls) td.className = c.cls
                tr.appendChild(td)
            })
        }
        tbody.appendChild(tr)
    })

    cmpEl.style.display = ""
}
```

**Column mapping** (6 columns — fits in 280–320 px panel):
| # | Header | Source field | Notes |
|---|--------|-------------|-------|
| 1 | Estrategia | `strategy_label` | truncate with CSS if too long |
| 2 | Ops | `closed_trades` | int |
| 3 | Win% | `win_rate` | float, 1 decimal |
| 4 | Max DD% | `max_drawdown` | float, 2 decimals |
| 5 | Ret% | `total_return_pct` | float, 2 decimals, sign |
| 6 | PF | `profit_factor` | float, 2 decimals (`"--"` if 0 or missing) |

Note: `profit_factor` is present in the TASK-027 single-backtest result but **not** listed in TASK-029's `StrategyComparisonEntry` fields. Felix must check whether `run_backtest_comparison` returns it. If not available, render `"--"` for that column on all rows. The Python spec for TASK-029 does not include `profit_factor` in the comparison summary — Grace recommends dropping that column and replacing it with `Retorno $` (`total_profit`) if `profit_factor` is unavailable. **Felix decision**: verify at implementation time by reading `_extract_comparison_summary` in the backend.

---

### 5. New Python methods (three new methods)

**Location**: After `_run_backtest_worker` and `_on_backtest_run` (~line 924). The three new methods go between `_on_backtest_run` (ends ~line 924) and whatever method follows it.

**Tolerance**: ±5 lines

**5a. `_on_backtest_compare`**

```python
def _on_backtest_compare(self, json_str: str):
    # Mirror of _on_backtest_run but for comparison mode.
    json_str = (json_str or "").strip()
    if not json_str:
        self.backtest_state["comparison_error"] = "Payload de comparación vacío"
        self._render_backtest_comparison_panel()
        return

    if self.backtest_state.get("comparison_running"):
        self.backtest_state["comparison_error"] = "Ya hay una comparación en ejecución"
        self._render_backtest_comparison_panel()
        return

    try:
        payload = json.loads(json_str)
    except Exception as error:
        self.backtest_state["comparison_error"] = f"Payload de comparación inválido: {error}"
        self._render_backtest_comparison_panel()
        return

    strategy_keys = list(payload.get("strategy_keys") or [])
    if len(strategy_keys) < 2:
        self.backtest_state["comparison_error"] = "Se requieren al menos 2 estrategias para comparar"
        self._render_backtest_comparison_panel()
        return

    # Resolve entries and modules for each key
    strategies = []
    for key in strategy_keys:
        entry = self._get_strategy_entry(key)
        if not entry:
            self.backtest_state["comparison_error"] = f"Estrategia no encontrada: {key}"
            self._render_backtest_comparison_panel()
            return
        if entry.get("module_obj") is None and not self._load_strategy_entry(entry):
            self.backtest_state["comparison_error"] = (
                entry.get("last_error") or f"No se pudo cargar: {key}"
            )
            self._render_backtest_comparison_panel()
            return
        strategies.append({
            "strategy_key":   entry["key"],
            "strategy_label": entry["label"],
            "module":         entry.get("module_obj"),
            "timeframe_value": entry.get("timeframe_value"),
        })

    symbol = str(payload.get("symbol") or "").strip()
    if not symbol:
        self.backtest_state["comparison_error"] = "Debe seleccionar un símbolo"
        self._render_backtest_comparison_panel()
        return

    try:
        initial_balance = float(payload.get("initial_balance") or 0.0)
    except Exception:
        initial_balance = 0.0
    if initial_balance <= 0:
        self.backtest_state["comparison_error"] = "El balance inicial debe ser mayor que cero"
        self._render_backtest_comparison_panel()
        return

    try:
        start_date = self._parse_backtest_date(payload.get("start_date"), end_of_day=False)
        end_date   = self._parse_backtest_date(payload.get("end_date"), end_of_day=True)
    except Exception as error:
        self.backtest_state["comparison_error"] = str(error)
        self._render_backtest_comparison_panel()
        return

    if end_date < start_date:
        self.backtest_state["comparison_error"] = "La fecha fin no puede ser anterior a la fecha inicio"
        self._render_backtest_comparison_panel()
        return

    request = {
        "symbol":          symbol,
        "start_date":      start_date,
        "end_date":        end_date,
        "initial_balance": initial_balance,
        "strategies":      strategies,
        "warmup_bars":     max(int(getattr(config, "BARS_HISTORY", 500) or 500), 500),
        "lot":             float(getattr(config, "LOT", 0.01) or 0.01),
        "sl_points":       float(getattr(config, "SL_POINTS", 0.0) or 0.0),
        "tp_points":       float(getattr(config, "TP_POINTS", 0.0) or 0.0),
    }
    self.backtest_state["comparison_running"] = True
    self.backtest_state["comparison_error"]   = ""
    self._render_backtest_comparison_panel()

    self.comparison_thread = threading.Thread(
        target=self._run_backtest_comparison_worker,
        args=(request,),
        daemon=True,
    )
    self.comparison_thread.start()
```

**5b. `_run_backtest_comparison_worker`**

```python
def _run_backtest_comparison_worker(self, request: dict):
    try:
        result = run_backtest_comparison(request)
    except Exception as error:
        result = {"status": "error", "error": str(error)}

    self.backtest_state["comparison_running"] = False
    if result.get("status") in ("success", "partial"):
        self.backtest_state["comparison_error"]  = result.get("error") or ""
        self.backtest_state["comparison_result"] = result
    else:
        self.backtest_state["comparison_error"]  = str(result.get("error") or "Error al ejecutar comparación")
        self.backtest_state["comparison_result"] = None
    self._render_backtest_comparison_panel()
```

**5c. `_render_backtest_comparison_panel`**

```python
def _render_backtest_comparison_panel(self):
    handler = getattr(self, "side_panel_handler", None)
    if not handler or not getattr(self, "chart", None):
        return
    payload = {
        "comparison_running": bool(self.backtest_state.get("comparison_running")),
        "comparison_result":  self.backtest_state.get("comparison_result"),
        "comparison_error":   str(self.backtest_state.get("comparison_error") or ""),
    }
    payload_json = json.dumps(payload, ensure_ascii=False)
    self.chart.run_script(f'''
        ;(function() {{
            const data = {payload_json};
            if (window.renderBacktestComparison) {{
                window.renderBacktestComparison(data);
            }}
        }})();
    ''')
```

---

### 6. New `backtest_compare` branch in `on_side_panel_event`

**Location**: After the `if action == "backtest_run" and args:` block (~line 5229–5232).

**What changes**: Insert immediately after that block:

```python
if action == "backtest_compare" and args:
    json_str = unquote(args[0]) if len(args) > 0 else ""
    self._on_backtest_compare(json_str)
    return
```

**What must NOT change**: The `backtest_run` branch above and the `strategy_builder_new` branch below.

---

## Alternation: Single vs Comparison mode

| Element | Single mode | Compare mode |
|---------|------------|--------------|
| `#tv-backtest-strategy` (select) | visible | `display:none` |
| `#tv-backtest-strategy-checks` | `display:none` | visible |
| `#tv-backtest-run` | visible | `display:none` |
| `#tv-backtest-compare-btn` | `display:none` | visible |
| `#tv-backtest-results` | shown by `renderBacktestPanel` | `display:none` |
| `#tv-backtest-extra-cards` | shown by `renderBacktestPanel` | `display:none` |
| `#tv-backtest-equity-section` | shown by `renderBacktestCharts` | `display:none` |
| `#tv-backtest-drawdown-section` | shown by `renderBacktestCharts` | `display:none` |
| `#tv-backtest-trades-section` | shown by `renderBacktestPanel` | `display:none` |
| `#tv-backtest-comparison-results` | `display:none` | shown by `renderBacktestComparison` |

The `applyMode` helper in `renderBacktestPanel` enforces this table on every panel re-render. `renderBacktestComparison` also enforces the "comparison hides single results" invariant defensively.

**Mode state persistence**: `state.backtest_mode` is stored in `window.tvBacktest.state` (JS-side). It survives `renderBacktestPanel` re-renders because `renderBacktestPanel` reads and respects `state.backtest_mode` before calling `applyMode`. It does NOT survive full page reloads (acceptable — default is "single").

---

## Invariant Checklist

- [x] No `chart.run_script()` from bot-loop or quote thread — comparison worker uses pre-existing backtest-worker exception pattern
- [x] DOM elements use `getElementById` guard before use in all new JS — every access is guarded with `if (!el) return` or ternary null check
- [x] New config accesses use `getattr(config, "KEY", default)` pattern — see `_on_backtest_compare` pseudocode
- [x] New `self.*` variables initialized before first use — `self.comparison_thread = None` and state keys added in `__init__` before any setup method that reads them
- [x] Strategy registry: untouched — comparison reads entries via `_get_strategy_entry` (existing method, main-thread safe) before spawning the thread; no registry writes from the comparison thread
- [x] New JS→Python action `"backtest_compare"` is unique — grepped, no collision in `gui_charts.py`
- [x] New DOM IDs are unique — grepped, no collision in `gui_charts.py`
- [x] Mode toggle buttons wired with `dataset.modeBound` / `dataset.compareBound` guard to prevent double-binding across `renderBacktestPanel` re-renders
- [x] Checkbox list is repopulated on every `renderBacktestPanel` call (same as the strategy `<select>`); previously checked state is preserved by re-reading checked checkboxes before clearing `innerHTML`
- [x] `#tv-backtest-comparison-results` starts `display:none` in the static HTML — never visible until `renderBacktestComparison` makes it visible
- [x] TASK-028 insertion points not overlapped — TASK-030's CSS goes after TASK-028's CSS; TASK-030's HTML goes after TASK-028's HTML additions; TASK-030's `renderBacktestPanel` extension goes after TASK-028's extension; `renderBacktestComparison` goes after TASK-028's `renderBacktestCharts`
- [x] `profit_factor` column: Felix must verify availability at implementation time (see note in section 4); render `"--"` if absent

---

## Notes for Felix

1. **Apply TASK-028 first, then TASK-030.** All TASK-030 insertion points are downstream of TASK-028's changes.

2. **`renderBacktestComparison` brace strategy**: Prefer the separate `chart.run_script()` approach (define the function at setup time in `_inject_custom_styles` or a dedicated injection method) so the function body is unescaped JS. Only `_render_backtest_comparison_panel`'s inline call needs escaping (`{{ }}` around the IIFE).

3. **`profit_factor` in comparison entries**: TASK-029's `StrategyComparisonEntry` does not list `profit_factor`. Before rendering the PF column, check `entry.hasOwnProperty("profit_factor")` or equivalent. If absent, render `"--"` for all rows and consider replacing the column header with `Profit $` backed by `total_profit`.

4. **`applyMode` visibility for single-mode sections**: Instead of `_lastDisplay` tricks, set display directly: in compare mode, force all single-result containers to `"none"`; in single mode, leave them at `""` (their CSS default is `display:none` per TASK-028's static HTML, so `""` is correct — `renderBacktestPanel` will set them visible when results are available).

5. **`comparison_running` in `renderBacktestPanel`**: The compare button's click handler checks `state.comparison_running` to prevent double-firing. This value must be added to `state` by `renderBacktestPanel`: `state.comparison_running = !!payloadData.comparison_running`. The payload must include it — but `_render_backtest_panel` (single mode) does NOT include it. Therefore `state.comparison_running` must default to `false` if absent from the payload (`!!payloadData.comparison_running` safely handles undefined as false).

6. **`run_backtest_comparison` import**: Add to the existing import line at the top of `gui_charts.py` where `run_backtest` is imported. Grep for `from backtesting` or `import run_backtest` to find the exact line.
