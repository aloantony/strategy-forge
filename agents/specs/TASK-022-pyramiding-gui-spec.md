# GUI Change Spec: Pyramiding and Risk Widget

**By**: Grace
**Date**: 2026-04-08
**Task**: TASK-022
**Status**: ready

---

## Summary

This spec covers two questions raised by TASK-022: (1) whether the existing chart marker system needs modifications to handle multiple pyramid entries per cycle, and (2) the full specification of a risk widget in the Estrategias tab showing aggregate risk vs. the 3% limit.

**Finding on markers**: No changes are needed. The current deal-grouping pipeline already handles multiple BUY entries per candle bucket with a count badge ("BUY x2") and a multi-entry tooltip. See §Marker System Decision for the full justification.

**Risk widget**: New DOM element `#tv-risk-widget` added to the Estrategias tab (inside `#tv-strategy-panel`), populated every bot loop cycle by a new `_update_risk_widget()` method. This method follows the exact same threading and data-access pattern as the existing `update_balance()`.

---

## Marker System Decision

### Decision: No changes required to the marker system.

**Justification**:

The pipeline in `update_chart()` (~lines 5335–5544) processes deals from `mt5.history_deals_get()`. Each position opened by `apply_pyramid_signal()` is recorded by MT5 as an independent deal with a unique `position_id`. The pipeline handles this correctly at every stage:

1. **Deduplication** (lines ~5401–5425): keyed by `(position_id, entry)`. Each pyramid position has a unique `position_id`, so no dedup collision occurs between pyramid entries.

2. **Bucket grouping** (lines ~5433–5449): deals are grouped by `bucket_time = (deal_time // bucket_seconds) * bucket_seconds`. Pyramid entries are triggered only when price has advanced ≥ 0.5×ATR from the previous entry price — typically 2–10+ candles apart on a DAX M1/M5 chart. Under normal market conditions, pyramid entries land in different buckets and each gets its own arrow marker.

3. **Same-bucket handling** (lines ~5451–5503): if two pyramid entries land in the same candle bucket (possible during volatile gaps), the code selects all same-direction deals in the bucket, sets `count = len(selected_deals)`, and produces text `"BUY x{count}"`. This is already correct behavior.

4. **Tooltip** (`_format_deal_group_tooltip`, lines ~5661–5732): iterates all deals in the group (up to `max_items=8`) with individual timestamp, price, volume, and P&L per line. Multiple pyramid entries render correctly already.

5. **Action markers** (`_set_action_markers`): one marker per bucket, regardless of how many deals are in that bucket. Correct for pyramids.

**What must NOT change as a result of this task**: None of the methods in the marker pipeline (`update_chart`, `_format_deal_group_tooltip`, `_set_action_markers`, `_ensure_action_tooltip`) should be touched by Felix for TASK-026.

---

## Affected Methods

| Method | File location (approx line) | Change type | Threading context |
|--------|---------------------------|-------------|-------------------|
| `__init__` | ~84 | modify (new instance var) | main |
| `_build_side_panel` | ~3431 | modify (add DOM element) | main |
| `_build_strategy_builder_ui` | ~1460 | modify (add CSS) | main |
| `_update_risk_widget` | new method, insert ~6450 (before `bot_loop`) | new | bot-loop |
| `bot_loop` | ~6560 | modify (call new method) | bot-loop |

---

## New Instance Variables

Add in `__init__` after line ~93 (`self._action_tooltip_ready = False`), alongside other state variables:

```python
self._current_aggregate_risk_pct = 0.0  # cached risk %, updated by _update_risk_widget
```

**Type**: `float`
**Initial value**: `0.0`
**Used by**: `_update_risk_widget()` (for caching only; not read elsewhere — the DOM is the source of truth for display)

---

## Threading Analysis

**Established pattern in this codebase**: `bot_loop()` directly calls `update_balance()`, `update_quotes()`, `_render_strategy_panel()`, and `update_chart()` — all of which call `self.chart.run_script()` from the bot-loop thread. This is the actual pattern, despite what `context.md` describes abstractly. There is no `_callback_queue` in the current code.

**`_update_risk_widget()`** must follow the same pattern:
- Called directly from `bot_loop()` after `update_balance()` (line ~6560)
- Calls `mt5.account_info()` and `mt5.positions_get()` from the bot-loop thread — same as existing bot_loop code
- Calls `self.chart.run_script()` directly from bot-loop thread — consistent with `update_balance()` and `_render_strategy_panel()`

No new threading mechanisms are needed. The method is structurally identical to `update_balance()`.

---

## JavaScript Interaction Points

### Risk widget DOM update

- **Pattern**: Python → JS with JSON
- **Trigger**: `_update_risk_widget()` called from `bot_loop` every cycle
- **Data crossing the boundary**: `{"risk_pct": float, "limit_pct": 3.0, "color": str}`
- **Handler registration**: none (Python→JS only; no JS→Python callback)
- **Brace budget**: 1 level of `{{ }}` in the IIFE wrapper; the payload itself is safe via `json.dumps`
- **Constraints**: Use `json.dumps({...})` + `const payload = {payload}` pattern. Element access must be guarded with `getElementById` null check.

**Pseudocode for the JS block inside `_update_risk_widget()`**:
```
payload = json.dumps({"risk_pct": risk_pct_rounded, "limit_pct": 3.0, "color": color_hex})
self.chart.run_script(f'''
    ;(function() {{
        const payload = {payload};
        const valEl = document.getElementById("tv-risk-value");
        const rowEl = document.getElementById("tv-risk-widget");
        if (!valEl || !rowEl) return;
        valEl.innerText = payload.risk_pct.toFixed(1) + "%";
        valEl.style.color = payload.color;
    }})();
''')
```

---

## Insertion Point Map

### 1. `__init__` — new instance variable

**Location**: After line ~94 (`self._action_tooltip_ready = False`)

**What changes**: Add one line: `self._current_aggregate_risk_pct = 0.0`

**What must NOT change**: The order of subsequent initializations (strategy registry, chart creation) is unchanged.

---

### 2. `_build_side_panel` — add risk widget element to `strategyPanel`

**Location**: Inside the `_build_side_panel` JS block, after `strategyPanel` is created (~line 3577, `strategyPanel.style.color = "#b0b0b0"`) and **before** `strategyPanel.appendChild(strategyList)` (~line 3704).

**What changes**: Add a risk widget `div` to `strategyPanel` using DOM construction (consistent with existing style in this method). Must use `getElementById` guard to avoid duplicates on rebuild.

**What must NOT change**: The creation or ordering of `strategyList`, `strategyEmpty`, `runBox`, `toggleBtn`, `addBox`. The `strategyPanel.appendChild(...)` calls at lines ~3704–3708 remain unchanged.

**Pseudocode** (JS within the IIFE in `_build_side_panel`):
```
// After strategyPanel is created, before strategyList is appended:

let riskWidget = document.getElementById("tv-risk-widget");
if (!riskWidget) {
    riskWidget = document.createElement("div");
    riskWidget.id = "tv-risk-widget";
    riskWidget.className = "tv-risk-widget";

    const riskLabel = document.createElement("span");
    riskLabel.className = "tv-risk-label";
    riskLabel.innerText = "Riesgo:";

    const riskValue = document.createElement("span");
    riskValue.id = "tv-risk-value";
    riskValue.className = "tv-risk-value";
    riskValue.innerText = "--";

    const riskSep = document.createElement("span");
    riskSep.className = "tv-risk-sep";
    riskSep.innerText = "/ 3.0%";

    riskWidget.appendChild(riskLabel);
    riskWidget.appendChild(riskValue);
    riskWidget.appendChild(riskSep);
}
strategyPanel.appendChild(riskWidget);   // ← BEFORE appendChild(strategyList)
```

Then `strategyPanel.appendChild(strategyList)` continues as before.

---

### 3. `_build_strategy_builder_ui` — add CSS for risk widget

**Location**: Inside the existing `style.textContent = \`...\`` block in `_build_strategy_builder_ui` (~line 1468). Add CSS rules at the end of the block, before the closing backtick.

**What changes**: Append 4 new CSS rules. The `if (document.getElementById("tv-builder-form-view")) return;` guard (line ~1464) already prevents double-injection.

**What must NOT change**: All existing `.tv-builder-*` rules are unchanged.

**CSS to append**:
```css
#tv-risk-widget {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px 6px 10px;
    font-size: 12px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    margin-bottom: 4px;
    flex-shrink: 0;
}
.tv-risk-label {
    color: rgba(255,255,255,0.45);
    font-size: 11px;
}
#tv-risk-value {
    font-weight: 600;
    color: #4CAF50;
    min-width: 36px;
}
.tv-risk-sep {
    color: rgba(255,255,255,0.3);
    font-size: 11px;
}
```

---

### 4. New method `_update_risk_widget()` — compute and render

**Location**: Insert as a new method before `bot_loop` (~line 6452). Place it in the "Bot loop and threading" section of the file.

**Threading context**: bot-loop thread (called from `bot_loop` directly, consistent with `update_balance()`).

**Pseudocode**:
```python
def _update_risk_widget(self):
    # Computes aggregate risk % for the currently selected strategy on config.SYMBOL
    # and updates #tv-risk-value in the DOM.
    # Called from bot_loop — runs on bot-loop thread, calls chart.run_script() directly.
    try:
        selected_entry = self._get_selected_strategy_entry()
        if not isinstance(selected_entry, dict):
            # No strategy selected — show placeholder
            risk_pct = 0.0
            color = "#888888"
        else:
            magic_number = int(selected_entry.get("magic_number") or 0)
            symbol = getattr(config, "SYMBOL", "")

            account = mt5.account_info()
            balance = account.balance if account is not None else 0.0
            if balance <= 0:
                risk_pct = 0.0
                color = "#888888"
            else:
                symbol_info = mt5.symbol_info(symbol)
                tick_size = getattr(symbol_info, "trade_tick_size", 0.0) or 0.0
                tick_value = getattr(symbol_info, "trade_tick_value", 0.0) or 0.0
                if tick_size <= 0 or tick_value <= 0:
                    risk_pct = 0.0
                    color = "#888888"
                else:
                    value_per_unit = tick_value / tick_size
                    all_positions = mt5.positions_get(symbol=symbol)
                    risk_money = 0.0
                    if all_positions:
                        for pos in all_positions:
                            if getattr(pos, "magic", None) != magic_number:
                                continue
                            if pos.type != mt5.ORDER_TYPE_BUY:
                                continue
                            sl = pos.sl
                            if sl <= 0:
                                continue
                            distance = pos.price_open - sl
                            if distance <= 0:
                                continue
                            risk_money += pos.volume * distance * value_per_unit
                    risk_pct = (risk_money / balance) * 100.0

                # Color coding: green < 2%, orange 2–3%, red >= 3%
                if risk_pct >= 3.0:
                    color = "#ef5350"   # red — at or over limit
                elif risk_pct >= 2.0:
                    color = "#ffaa00"   # orange — approaching limit
                else:
                    color = "#4CAF50"   # green — safe

        self._current_aggregate_risk_pct = risk_pct

        payload = json.dumps({
            "risk_pct": round(risk_pct, 2),
            "color": color,
        })
        self.chart.run_script(f'''
            ;(function() {{
                const payload = {payload};
                const valEl = document.getElementById("tv-risk-value");
                if (!valEl) return;
                valEl.innerText = payload.risk_pct.toFixed(1) + "%";
                valEl.style.color = payload.color;
            }})();
        ''')
    except Exception as e:
        self.log_message(f"Error actualizando widget de riesgo: {e}")
```

**Note on brace escaping**: The outer f-string (the `run_script` call) requires `{{` / `}}` for literal JS braces. The payload is safe from brace-escaping because it is produced by `json.dumps()` before insertion. The `except` clause uses a separate, plain f-string — `{e}` there is a normal Python interpolation, no escaping needed.

---

### 5. `bot_loop` — call `_update_risk_widget()`

**Location**: Line ~6560, immediately after `self.update_balance()`.

**Current code** (lines 6560–6562):
```python
self.update_balance()
self.update_quotes()
self._render_strategy_panel()
```

**After change**:
```python
self.update_balance()
self._update_risk_widget()
self.update_quotes()
self._render_strategy_panel()
```

**What must NOT change**: `update_balance()`, `update_quotes()`, `_render_strategy_panel()` calls remain unchanged and in their existing order. Only `self._update_risk_widget()` is inserted between `update_balance()` and `update_quotes()`.

---

## Invariant Checklist

- [x] **`chart.run_script()` threading**: Called from bot-loop thread in `_update_risk_widget()` — consistent with `update_balance()`, `_render_strategy_panel()`, `update_chart()` already doing this. No new threading violation introduced.
- [x] **DOM guard**: `_build_side_panel` creates `#tv-risk-widget` only if `getElementById("tv-risk-widget")` returns null — prevents duplicate elements if panel is rebuilt.
- [x] **DOM guard in update**: `_update_risk_widget()` JS block checks `if (!valEl) return` before accessing element.
- [x] **Config access pattern**: `getattr(config, "SYMBOL", "")` used — consistent with existing defensive config access.
- [x] **New instance variable**: `self._current_aggregate_risk_pct` initialized in `__init__` before `_inject_custom_styles()` and `setup_side_panel()` are called.
- [x] **Strategy registry**: `_update_risk_widget()` only reads the registry (via `_get_selected_strategy_entry()`) — no writes. Registry write invariant preserved.
- [x] **No new JS→Python handler**: The risk widget is pure Python→JS. No new handler name needed; no collision risk.
- [x] **`getElementById` guard in CSS injection**: `_build_strategy_builder_ui` already guards with `if (document.getElementById("tv-builder-form-view")) return;` — CSS is injected only once.
- [x] **Future Backtest tab**: `_build_side_panel` hardcodes three tabs (Strategy Data, Data Window, Estrategias). The risk widget is inside `#tv-strategy-panel`, which is the content div for the Estrategias tab. Adding a fourth Backtest tab in a future sprint only requires adding a new content div — the risk widget placement is unaffected.
- [x] **`json` import**: Already imported at file top (`import json`). No new import needed.
- [x] **`mt5` import**: Already used throughout the file. No new import needed.

---

## Summary for Felix (TASK-026)

Felix must make exactly **5 targeted changes** to `gui_charts.py`:

1. **`__init__`** (~line 94): add `self._current_aggregate_risk_pct = 0.0`

2. **`_build_strategy_builder_ui`** (~line 1516, end of `style.textContent`): append 4 CSS rules for `#tv-risk-widget`, `.tv-risk-label`, `#tv-risk-value`, `.tv-risk-sep`

3. **`_build_side_panel`** (~line 3700, after `strategyPanel.style.color` assignment): add JS DOM construction for `#tv-risk-widget` with `getElementById` guard, append to `strategyPanel` before `strategyPanel.appendChild(strategyList)`

4. **New method `_update_risk_widget()`** (insert before `bot_loop` at ~line 6452): compute aggregate risk from live MT5 positions for the selected strategy's magic_number, update DOM via `json.dumps` + `chart.run_script()`

5. **`bot_loop`** (~line 6560): insert `self._update_risk_widget()` call between `update_balance()` and `update_quotes()`

**Do NOT touch**: `update_chart()`, `_format_deal_group_tooltip()`, `_set_action_markers()`, `_ensure_action_tooltip()`, `setup_side_panel()`, `on_side_panel_event()`, any marker-related code.
