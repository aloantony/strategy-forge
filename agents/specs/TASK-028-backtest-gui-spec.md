# GUI Change Spec: Backtest — tabla de trades, equity curve y drawdown

**By**: Grace
**Date**: 2026-04-11
**Task**: TASK-028
**Status**: ready

---

## Summary

This spec adds three new visual sections to the existing backtest panel: four extra metric cards (profit_factor, avg_win, avg_loss, expectancy), an equity curve SVG micro-chart, and a drawdown SVG micro-chart — plus a scrollable trades table. The panel form, the 8 existing cards, the threading model, and the JS→Python callback flow are all unchanged. The only Python change is in `_render_backtest_panel` (~line 795): strip `equity_curve` and `drawdown_curve` from the first run_script payload (they can be 12–25 MB of JSON for M1/1yr) and dispatch them in a second run_script immediately after. This is safe to implement now; TASK-027 backend changes are done (spec status: ready).

---

## Affected Methods

| Method | File location (approx line) | Change type | Threading context |
|--------|---------------------------|-------------|-------------------|
| `_render_backtest_panel` | ~795 | modify | backtest-worker thread — established exception: calls `chart.run_script()` directly (pre-existing pattern, not via callback_queue; do not change) |

No new methods, no new instance variables.

---

## New Instance Variables

None. All state is local to the JS `window.tvBacktest.state` object already established.

---

## Threading Analysis

`_render_backtest_panel` is called from `_run_backtest_worker` running in `self.backtest_thread`. This thread already calls `chart.run_script()` directly — a pre-established exception to the callback-queue rule documented in `context.md`. This spec adds **one additional `chart.run_script()` call** in the same method, immediately after the existing call. This stays within the established pattern. No new threading context is introduced.

Confirm: **No `chart.run_script()` call from bot-loop or quote thread.** The backtest-worker thread is a separate, purpose-built thread whose direct `run_script` access is pre-approved by the existing code.

---

## JavaScript Interaction Points

### 1. Panel render (existing, modified payload)

- **Pattern**: Python→JS with JSON
- **Trigger**: `_render_backtest_panel` called at backtest completion
- **Data crossing**: The full payload dict, **minus** `equity_curve` and `drawdown_curve` from within `result`. All other result fields (profit_factor, avg_win, avg_loss, expectancy, trades, etc.) remain in the payload.
- **Brace budget**: 2 levels (outer IIFE `{{ }}` + `if (window.renderBacktestPanel) {{ }}`)
- **Constraints**: `payload_json = json.dumps(panel_payload, ensure_ascii=False)` — same as today; the only change is that `panel_payload["result"]` is a shallow copy with `equity_curve`/`drawdown_curve` popped before serialization.

### 2. Chart data dispatch (new, second run_script)

- **Pattern**: Python→JS with JSON
- **Trigger**: Immediately after the first run_script in `_render_backtest_panel`, only when there is a non-empty `equity_curve` or `drawdown_curve`.
- **Data crossing**: `{"equity_curve": list[dict], "drawdown_curve": list[dict], "initial_balance": float}`
- **Called function**: `window.renderBacktestCharts(chartsData)` — a new window-level function defined adjacent to `renderBacktestPanel`.
- **Brace budget**: 1 level (the outer IIFE `{{ }}`)
- **Constraints**: The first run_script must render the DOM containers (`#tv-backtest-equity-svg`, `#tv-backtest-drawdown-svg`) before this call runs. Since both calls originate from the same Python thread and `run_script` dispatches in order to the webview, this ordering is guaranteed.

No new JS→Python handlers. All new sections are data-driven from the payload; user does not interact with charts or table (read-only display).

---

## Payload Decision: Two run_scripts

**Decision**: Send `equity_curve` and `drawdown_curve` in a **second** `run_script` call, separate from the panel render.

**Justification**:
- M1/1yr backtest produces ~120,000–250,000 equity_curve points. Each entry `{"time": int, "equity": float, "balance": float}` serializes to ~50 chars. At 250k points × 50 chars × 2 curves = **~25 MB of JSON** injected into a single f-string.
- A 25 MB string passed to `run_script` risks JS parse latency, WebView memory pressure, and potential OOM in the embedded browser.
- Splitting into two calls: first call (<1 MB, all summary data) renders instantly; second call (chart data only) is dispatched immediately after and renders the SVG asynchronously.
- Both calls still come from the same backtest-worker thread — no threading change.
- The extra cards and trades table are included in the **first** run_script (they are part of `result` and are not large).

---

## SVG vs Canvas Decision

**Decision**: SVG (`<svg>`, polyline / path elements).

**Justification**:
- The backtest panel lives inside the side panel HTML (not a lightweight_charts sub-chart) — SVG is native HTML, requires no getContext() call, and renders inline in the webview's HTML engine.
- The charts are static (rendered once per backtest run, not animated or real-time). SVG is optimal for static renders.
- JS-side downsampling to ≤300 points produces a polyline string of ~3–5 KB — trivial DOM size.
- No external dependencies required.
- Canvas would require `canvas.getContext("2d")`, imperative draw calls, and explicit width/height in pixels. SVG with `preserveAspectRatio="none"` scales automatically with CSS.

---

## Insertion Point Map

### 1. New CSS classes in `_inject_custom_styles`

**Location**: After line ~3326 (closing `}` of `.tv-backtest-card-value { }`), before line ~3327 (`.tv-confirm-overlay {`)

**Tolerance**: ±5 lines

**What changes**: Insert the following CSS block (it is inside the f-string; all `{` / `}` must be escaped as `{{` / `}}`):

```css
.tv-backtest-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.tv-backtest-section-title {
    font-size: 11px;
    color: #8f8f8f;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.tv-backtest-microchart {
    width: 100%;
    height: 60px;
    display: block;
    border-radius: 4px;
    background: #1a1a1a;
    overflow: visible;
}
.tv-backtest-trades-wrapper {
    overflow-x: auto;
    max-height: 220px;
    overflow-y: auto;
}
.tv-backtest-trades-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 10px;
    color: #c0c0c0;
    min-width: 420px;
}
.tv-backtest-trades-table th {
    font-size: 9px;
    color: #8f8f8f;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 4px 5px;
    background: #1a1a1a;
    position: sticky;
    top: 0;
    z-index: 1;
    border-bottom: 1px solid #2f2f2f;
    white-space: nowrap;
}
.tv-backtest-trades-table td {
    padding: 4px 5px;
    border-bottom: 1px solid #252525;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.tv-backtest-trades-table tr:hover td {
    background: #1f1f1f;
}
.tv-backtest-trade-win {
    color: #5cb85c;
}
.tv-backtest-trade-loss {
    color: #d9534f;
}
```

**What must NOT change**: The `.tv-backtest-card-value` block above and the `.tv-confirm-overlay` block below must remain untouched.

---

### 2. New HTML sections in `backtestPanel.innerHTML` (in `_build_side_panel`)

**Location**: After line ~4020 (`<div class="tv-backtest-results" id="tv-backtest-results"></div>`), before the closing backtick `` ` `` that ends `backtestPanel.innerHTML` at line ~4021.

**Tolerance**: ±5 lines

**What changes**: Insert four new HTML sections as the last children of the backtestPanel's innerHTML template. These elements start hidden (`style="display:none"`) and are shown by the JS render functions only when a successful result is available.

```html
<div class="tv-backtest-results" id="tv-backtest-extra-cards" style="display:none;"></div>
<div class="tv-backtest-section" id="tv-backtest-equity-section" style="display:none;">
    <div class="tv-backtest-section-title">Curva de equity</div>
    <svg class="tv-backtest-microchart" id="tv-backtest-equity-svg"
         viewBox="0 0 280 60" preserveAspectRatio="none"></svg>
</div>
<div class="tv-backtest-section" id="tv-backtest-drawdown-section" style="display:none;">
    <div class="tv-backtest-section-title">Drawdown</div>
    <svg class="tv-backtest-microchart" id="tv-backtest-drawdown-svg"
         viewBox="0 0 280 60" preserveAspectRatio="none"></svg>
</div>
<div class="tv-backtest-section" id="tv-backtest-trades-section" style="display:none;">
    <div class="tv-backtest-section-title">Trades</div>
    <div class="tv-backtest-trades-wrapper">
        <table class="tv-backtest-trades-table" id="tv-backtest-trades-table">
            <thead>
                <tr>
                    <th>#</th>
                    <th>Tipo</th>
                    <th>Hora ent.</th>
                    <th>Hora sal.</th>
                    <th>P. ent.</th>
                    <th>P. sal.</th>
                    <th>P&amp;L</th>
                    <th>Razón</th>
                </tr>
            </thead>
            <tbody id="tv-backtest-trades-tbody"></tbody>
        </table>
    </div>
</div>
```

**DOM element IDs introduced** (must be unique in the page — grepped, no collisions):
- `tv-backtest-extra-cards`
- `tv-backtest-equity-section`
- `tv-backtest-equity-svg`
- `tv-backtest-drawdown-section`
- `tv-backtest-drawdown-svg`
- `tv-backtest-trades-section`
- `tv-backtest-trades-table`
- `tv-backtest-trades-tbody`

**What must NOT change**: The `<div id="tv-backtest-results">` line above must remain untouched. The existing 8 cards still render into `#tv-backtest-results` — this is unmodified.

---

### 3. Extra cards + trades JS inside `renderBacktestPanel`

**Location**: After line ~4593 (closing `}});` of the `cards.forEach(...)` block), before line ~4594 (closing `}};` of `renderBacktestPanel`).

**Tolerance**: ±5 lines

**What changes**: Append the following block at the end of `renderBacktestPanel`, after the existing `cards.forEach` loop. This code:
1. Hides the new sections if result is absent/failed (defensive reset)
2. Renders the 4 extra metric cards into `#tv-backtest-extra-cards`
3. Renders the trades table into `#tv-backtest-trades-tbody`

Note: The equity/drawdown SVGs are **not** rendered here — they are populated by `window.renderBacktestCharts` (second run_script). This block only manages visibility and the table.

Because this code is inside an f-string, **all `{` and `}` in the JavaScript must be escaped as `{{` and `}}`**. String template literals (backtick strings) inside this block must use `{{}}` for JS object literals. Prefer `document.createElement` + property assignment over innerHTML with template literals to avoid brace-escaping issues in nested structures.

**Pseudocode (Felix translates to escaped f-string JS)**:

```
// --- Extra section reset (runs every renderBacktestPanel call) ---
extraCardsEl = getElementById("tv-backtest-extra-cards")
equitySection = getElementById("tv-backtest-equity-section")
drawdownSection = getElementById("tv-backtest-drawdown-section")
tradesSection = getElementById("tv-backtest-trades-section")

if extraCardsEl: extraCardsEl.style.display = "none"
if equitySection: equitySection.style.display = "none"
if drawdownSection: drawdownSection.style.display = "none"
if tradesSection: tradesSection.style.display = "none"

if NOT state.result OR state.result.status != "success":
    return  // already returned above in existing code; this block only runs after that guard

// --- 4 extra metric cards ---
if extraCardsEl:
    extraCards = [
        ["Profit Factor", formatFixed(result.profit_factor, 2)],
        ["Avg Win",       formatMoney(result.avg_win)],
        ["Avg Loss",      formatMoney(result.avg_loss)],
        ["Expectancy",    formatMoney(result.expectancy)],
    ]
    extraCardsEl.innerHTML = ""
    for each [label, value] in extraCards:
        card = createElement("div"); card.className = "tv-backtest-card"
        labelEl = createElement("div"); labelEl.className = "tv-backtest-card-label"; labelEl.innerText = label
        valueEl = createElement("div"); valueEl.className = "tv-backtest-card-value"; valueEl.innerText = value
        card.append(labelEl, valueEl)
        extraCardsEl.appendChild(card)
    extraCardsEl.style.display = ""

// --- Trades table ---
trades = Array.isArray(result.trades) ? result.trades : []
if tradesSection AND trades.length > 0:
    tbody = getElementById("tv-backtest-trades-tbody")
    if tbody:
        tbody.innerHTML = ""
        for idx, trade in enumerate(trades):
            pnl = Number(trade.profit || 0)
            pnlClass = pnl > 0 ? "tv-backtest-trade-win" : pnl < 0 ? "tv-backtest-trade-loss" : ""
            tipo = trade.direction === 1 ? "BUY" : "SELL"
            entryTime = tvBacktest.formatDateTime(trade.entry_time)
            exitTime  = tvBacktest.formatDateTime(trade.exit_time)
            entryPx   = Number(trade.entry_price || 0).toFixed(2)
            exitPx    = Number(trade.exit_price  || 0).toFixed(2)
            pnlText   = (pnl >= 0 ? "+" : "") + pnl.toFixed(2)
            reason    = String(trade.reason || "")

            row = createElement("tr")
            // Build each td manually to avoid brace-escaping issues:
            cells = [
                String(idx + 1),   // #
                tipo,              // Tipo
                entryTime,         // Hora ent.
                exitTime,          // Hora sal.
                entryPx,           // P. ent.
                exitPx,            // P. sal.
                pnlText,           // P&L  (styled with pnlClass on this td only)
                reason,            // Razón
            ]
            cells.forEach((text, colIdx) => {
                td = createElement("td")
                if colIdx === 6: td.className = pnlClass  // P&L column
                td.innerText = text
                row.appendChild(td)
            })
            tbody.appendChild(row)
    tradesSection.style.display = ""
```

**Field mapping** (confirmed from `backtesting/runtime.py` ~line 301):
- `trade.direction` — integer: `1` = BUY, `-1` = SELL (stored as `position["type"]`)
- `trade.entry_time` — epoch int UTC (from `_time_to_epoch`)
- `trade.exit_time` — epoch int UTC (from `_time_to_epoch`)
- `trade.entry_price` — float
- `trade.exit_price` — float
- `trade.profit` — float (positive = win, negative = loss)
- `trade.reason` — string ("SL", "TP", "REVERSAL", "FORCED", etc.)

---

### 4. New `window.tvBacktest.formatDateTime` helper

**Location**: Inside the existing JS block where `window.tvBacktest.formatDate` is defined, at line ~4419–4424.

**What changes**: Add `tvBacktest.formatDateTime` immediately after `tvBacktest.formatDate`. This helper shows date + HH:MM for trade timestamps, which are intraday.

**What must NOT change**: `formatDate` and `formatMoney` above must remain untouched.

**Pseudocode**:

```
window.tvBacktest.formatDateTime = (epoch) => {
    if epoch === null or undefined: return "--"
    dt = new Date(Number(epoch) * 1000)
    if isNaN(dt.getTime()): return "--"
    dateStr = dt.toLocaleDateString(undefined, { month: "2-digit", day: "2-digit" })
    timeStr = dt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })
    return dateStr + " " + timeStr
}
```

---

### 5. New `window.renderBacktestCharts` function

**Location**: After line ~4594 (closing `}};` of `renderBacktestPanel`), before line ~4596 (`window.tvEyeSvg = ...`).

**Tolerance**: ±5 lines

**What changes**: Insert a new window-level function. Because this is inside the same f-string as `renderBacktestPanel`, all JS `{` / `}` must be escaped as `{{` / `}}`.

This function is called by the second Python `run_script` with `{"equity_curve": [...], "drawdown_curve": [...], "initial_balance": float}`.

**Pseudocode**:

```
window.renderBacktestCharts = (data) => {
    equityCurve   = Array.isArray(data.equity_curve)   ? data.equity_curve   : []
    drawdownCurve = Array.isArray(data.drawdown_curve) ? data.drawdown_curve : []
    initialBal    = Number(data.initial_balance || 10000)

    equitySection   = getElementById("tv-backtest-equity-section")
    drawdownSection = getElementById("tv-backtest-drawdown-section")
    equitySvg       = getElementById("tv-backtest-equity-svg")
    drawdownSvg     = getElementById("tv-backtest-drawdown-svg")

    // ---- Helper: downsample array to max maxPts entries ----
    downsample = (arr, maxPts) => {
        if arr.length <= maxPts: return arr
        step = Math.floor(arr.length / maxPts)
        return arr.filter((_, i) => i % step === 0)
    }

    // ---- Helper: map data values to SVG coordinate strings ----
    // Returns array of "x,y" strings (SVG user-space coords)
    // W=280, H=60, PAD=4 (matches viewBox "0 0 280 60")
    toPoints = (samples, getVal) => {
        if samples.length < 2: return []
        vals = samples.map(getVal)
        minV = Math.min(...vals)
        maxV = Math.max(...vals)
        rangeV = maxV - minV || 1
        W = 280; H = 60; PAD = 4
        return samples.map((_, i) => {
            x = (i / (samples.length - 1)) * W
            y = PAD + (1 - (vals[i] - minV) / rangeV) * (H - 2 * PAD)
            return x.toFixed(1) + "," + y.toFixed(1)
        })
    }

    // ---- Equity curve (polyline, green if final >= initial, else red) ----
    if equitySvg AND equityCurve.length >= 2:
        samples    = downsample(equityCurve, 300)
        pts        = toPoints(samples, p => p.equity)
        finalEq    = samples[samples.length - 1].equity
        lineColor  = finalEq >= initialBal ? "#26a69a" : "#ef5350"
        // Build polyline element (avoid innerHTML with large strings; use setAttribute)
        equitySvg.innerHTML = ""
        poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline")
        poly.setAttribute("points", pts.join(" "))
        poly.setAttribute("fill", "none")
        poly.setAttribute("stroke", lineColor)
        poly.setAttribute("stroke-width", "1.5")
        poly.setAttribute("stroke-linejoin", "round")
        poly.setAttribute("stroke-linecap", "round")
        equitySvg.appendChild(poly)
        if equitySection: equitySection.style.display = ""

    // ---- Drawdown curve (filled area, red) ----
    // Orientation: 0% drawdown at top (y=PAD), max drawdown at bottom (y=H-PAD)
    // Fill: from plotted line UP to the top baseline (y=PAD)
    if drawdownSvg AND drawdownCurve.length >= 2:
        samples  = downsample(drawdownCurve, 300)
        pts      = toPoints(samples, p => p.drawdown_pct)
        W = 280; PAD = 4; H = 60
        // Build closed SVG path:
        //   M 0,PAD                            <- start at top-left baseline
        //   L pts[0] L pts[1] ... L pts[N-1]   <- follow drawdown line downward
        //   L W,PAD                            <- back to top-right baseline
        //   Z                                  <- close (draws back along top)
        pathD = "M 0," + PAD + " L " + pts.join(" L ") + " L " + W + "," + PAD + " Z"
        drawdownSvg.innerHTML = ""
        pathEl = document.createElementNS("http://www.w3.org/2000/svg", "path")
        pathEl.setAttribute("d", pathD)
        pathEl.setAttribute("fill", "rgba(239,83,80,0.25)")
        pathEl.setAttribute("stroke", "#ef5350")
        pathEl.setAttribute("stroke-width", "1.2")
        pathEl.setAttribute("stroke-linejoin", "round")
        drawdownSvg.appendChild(pathEl)
        if drawdownSection: drawdownSection.style.display = ""
}
```

**Brace budget**: This function is inside the CSS/JS f-string where `{{` / `}}` are escaped. Felix must escape every JS `{` / `}` except those that are Python f-string interpolations. Since `renderBacktestCharts` receives a JSON payload (not an f-string interpolation), there are **no Python interpolations** inside this function body — every `{` / `}` must be escaped as `{{` / `}}`.

**Recommended alternative to avoid brace explosion**: Define `renderBacktestCharts` in its own `self.chart.run_script()` call at GUI setup time (e.g., at the end of `_inject_custom_styles` or in a dedicated `_inject_backtest_chart_scripts` method). This way the function body is written in plain JS (unescaped), and only the data call needs escaping. This is the **preferred implementation path** if the brace count becomes unwieldy.

---

### 6. Python `_render_backtest_panel` changes

**Location**: Lines ~795–809.

**Tolerance**: ±5 lines

**Current code** (simplified):
```python
def _render_backtest_panel(self):
    handler = getattr(self, "side_panel_handler", None)
    if not handler or not getattr(self, "chart", None):
        return
    payload = self._get_backtest_payload()
    payload["handler"] = handler
    payload_json = json.dumps(payload, ensure_ascii=False)
    self.chart.run_script(f'''
        ;(function() {{
            const payload = {payload_json};
            if (window.renderBacktestPanel) {{
                window.renderBacktestPanel(payload);
            }}
        }})();
    ''')
```

**New code** (pseudocode — Felix translates):

```python
def _render_backtest_panel(self):
    handler = getattr(self, "side_panel_handler", None)
    if not handler or not getattr(self, "chart", None):
        return
    payload = self._get_backtest_payload()
    payload["handler"] = handler

    # Extract large array fields before serializing the panel payload
    result_raw = payload.get("result") or {}
    equity_curve   = result_raw.get("equity_curve") or []
    drawdown_curve = result_raw.get("drawdown_curve") or []
    initial_balance = float(result_raw.get("initial_balance") or 10000.0)

    # Build panel payload without the large arrays
    result_for_panel = {k: v for k, v in result_raw.items()
                        if k not in ("equity_curve", "drawdown_curve")}
    panel_payload = dict(payload)
    panel_payload["result"] = result_for_panel if result_raw else None

    panel_json = json.dumps(panel_payload, ensure_ascii=False)
    self.chart.run_script(f'''
        ;(function() {{
            const payload = {panel_json};
            if (window.renderBacktestPanel) {{
                window.renderBacktestPanel(payload);
            }}
        }})();
    ''')

    # Second run_script: chart data (only when result is present)
    if equity_curve or drawdown_curve:
        charts_json = json.dumps({{
            "equity_curve":   equity_curve,
            "drawdown_curve": drawdown_curve,
            "initial_balance": initial_balance,
        }}, ensure_ascii=False)
        self.chart.run_script(f'''
            ;(function() {{
                const chartsData = {charts_json};
                if (window.renderBacktestCharts) {{
                    window.renderBacktestCharts(chartsData);
                }}
            }})();
        ''')
```

**Note**: The dict comprehension `{k: v for k, v in result_raw.items() if k not in (...)}` must be written as a regular Python expression, not as an f-string literal. Felix must be careful: the `json.dumps({{ ... }})` for `charts_json` must use actual Python curly braces (not f-string interpolation), since `charts_json` is built before the f-string.

**What must NOT change**: The `_get_backtest_payload` method is untouched. The `backtest_state["result"]` stored in memory still contains the full result including `equity_curve` and `drawdown_curve`; we only strip them from the payload dict passed to `json.dumps`, not from the stored state.

---

## Invariant Checklist

- [x] No `chart.run_script()` from non-main-thread context — the backtest-worker thread's direct `run_script` access is a pre-existing, established exception documented in the codebase. No new threading patterns introduced.
- [x] DOM elements use `getElementById` guard before use — all `getElementById` calls in JS are guarded with `if (element)` before any property access.
- [x] New config accesses: none — no new `config.*` references.
- [x] New `self.*` variables: none — no new instance variables.
- [x] Strategy registry: untouched.
- [x] `renderBacktestPanel` idempotency: the new sections start hidden (`display:none`) in the static HTML and are shown/hidden by JS on each call. No new DOM elements are created — only existing elements' content and visibility are updated. The `innerHTML = ""` reset on `extraCardsEl` and `tbody` prevents duplicate content on repeated renders.
- [x] No new JS→Python handler names.
- [x] The existing 8 cards render path (`resultsEl.innerHTML = ""` loop at line ~4580–4592) is untouched.
- [x] The four new HTML sections are added **after** `#tv-backtest-results`, not before or inside it — the existing cards layout is preserved.

---

## Notes for Felix

1. **Brace escaping priority**: All JS code inside the existing `_inject_custom_styles` f-string must use `{{` / `}}` for literal JS braces. The safest path for `renderBacktestCharts` is to define it in a **separate** `chart.run_script()` call at setup time (e.g., at the end of `_inject_custom_styles`), so the function body is unescaped and only the data invocation needs escaping.

2. **`formatDateTime` helper**: Define it in the same JS block where `formatDate` is defined (~line 4419). It must be defined before `renderBacktestPanel` runs (same block, defined earlier → OK).

3. **`direction` field**: Confirmed from `backtesting/runtime.py` line 307: `"direction": position["type"]`. Felix must verify the type values by checking `_new_position` call sites in `runtime.py`. Based on `_apply_standard_signal` pseudocode in TASK-027: `direction = 1 if signal == "buy" else -1`. So `trade.direction === 1` is BUY, `-1` is SELL.

4. **SVG namespace**: `document.createElementNS("http://www.w3.org/2000/svg", "polyline")` — must use the SVG namespace for SVG child elements. Plain `createElement` will not render correctly.

5. **`preserveAspectRatio="none"`**: Critical on the `<svg>` element so the chart stretches to fill the container width regardless of content aspect ratio. Already specified in the HTML template above.

6. **Second run_script timing**: The two `chart.run_script()` calls are sequential in the Python thread. The WebView executes them in order. The first call establishes the DOM (shows `#tv-backtest-equity-section`, etc. ... no wait, actually the first call's JS **resets** those sections to `display:none` and the second call's `renderBacktestCharts` shows them). This ordering is correct.

7. **`#tv-backtest-extra-cards`** shares the class `tv-backtest-results` for consistent card grid styling (2-column grid). This reuses existing CSS.
