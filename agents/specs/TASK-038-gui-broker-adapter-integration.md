# GUI Change Spec: Migrate gui_charts.py trading.* calls to MT5BrokerAdapter

**By**: Grace
**Date**: 2026-04-13
**Task**: TASK-038
**Status**: ready

---

## Backend Summary

TASK-034 defined `IBrokerAdapter` (`src/broker/interface.py`) and `MT5BrokerAdapter` (`src/broker/mt5_adapter.py`). TASK-035 implemented both files. The interface exposes: `apply_signal`, `apply_pyramid_signal`, `is_market_open`, `get_open_positions`, `get_account_info`, `get_instrument_info`, `send_order`, `close_position`, `modify_sl`.

Two functions are NOT in the adapter interface and remain callable directly on `trading`:
- `trading.decode_trade_comment(comment)` — pure string parser, no MT5 calls
- `trading.calculate_dynamic_lot(atr_value, volume_ratio, instrument_info, balance)` — pure math, no MT5 calls (already updated signature from TASK-035)

`ExecutionEngine` is NOT used in `gui_charts.py` — it lives only in `main.py`. The task premise describing it being wired to `trading_module` is pre-TASK-035; that concern is already resolved in `main.py`.

---

## Summary

`gui_charts.py` (8316 lines) calls `trading.is_market_open`, `trading.apply_signal`, and `trading.apply_pyramid_signal` directly in two locations: the `on_quick_trade` event handler and the `bot_loop` background thread. It also already does an inline `MT5BrokerAdapter()` instantiation inside `bot_loop` each iteration (lines 8175–8178) to call `get_account_info` and `get_instrument_info`.

This spec migrates all those execution calls to a single `self._broker: MT5BrokerAdapter` instance initialized in `__init__`. The `trading` module import stays for `decode_trade_comment` and `calculate_dynamic_lot`. No chart JS is touched. No new handler is added.

---

## Affected Methods

| Method | File location (approx line) | Change type | Threading context |
|--------|---------------------------|-------------|-------------------|
| `__init__` | ~94 | modify — add `self._broker` init | main |
| `on_quick_trade` | ~4096 | modify — replace 2 `trading.*` calls | main |
| `bot_loop` | ~8116 | modify — replace inline `_Adapter()` + 3 `trading.*` calls | bot-loop |

---

## New Instance Variables

| Variable | Type | Initial value | Where in `__init__` |
|----------|------|---------------|----------------------|
| `self._broker` | `MT5BrokerAdapter` | `MT5BrokerAdapter()` | After line ~162 (`self._init_strategy_registry()`), before line ~164 (`_patch_lightweight_charts_js_worker()`) |

`MT5BrokerAdapter()` is stateless — it does not establish a connection at construction. Placing it here is safe.

---

## Threading Analysis

### `on_quick_trade` — main thread

`on_quick_trade` is a chart event handler registered via `window.callbackFunction` → `self.chart.win.handlers`. It runs on the main thread. The two calls to `self._broker.is_market_open()` and `self._broker.apply_signal()` are pure MT5 calls — they do NOT touch `chart.run_script()`. No threading issue.

### `bot_loop` — bot-loop thread

`bot_loop` runs in `self.bot_thread` (a daemon thread launched in `start_bot`). The calls being migrated (`is_market_open`, `apply_pyramid_signal`, `apply_signal`) are trade-execution calls — they do NOT call `chart.run_script()`. The callback queue pattern is not involved.

The existing pattern is already correct: `update_last_action_ui(action_info)` after execution uses the callback queue to push GUI updates back to the main thread. This spec does not change that.

**Confirm**: No `chart.run_script()` call is added or moved. The callback queue pattern is preserved as-is.

---

## JavaScript Interaction Points

None. This change has no JavaScript interaction. No new JS is injected, no new handler is registered, no cross-boundary data.

---

## Insertion Point Map

### 1. New import — top of file (~line 32)

**Location**: Line 32 (`import trading`). Add the new import on the line immediately after.

**What changes**: Add one import line:
```python
from src.broker.mt5_adapter import MT5BrokerAdapter
```

**What must NOT change**: The existing `import trading` line stays — it is still needed for `decode_trade_comment` and `calculate_dynamic_lot`.

---

### 2. `__init__` — new `self._broker` (~line 162–164)

**Location**: After `self._init_strategy_registry()` (~line 162), before `_patch_lightweight_charts_js_worker()` (~line 164).

**What changes**: Insert one line:
```python
self._broker = MT5BrokerAdapter()
```

**What must NOT change**: The call order `_init_strategy_registry()` → `_patch_...` → `Chart(...)` must be preserved. The new line goes between `_init_strategy_registry()` and `_patch_...`.

---

### 3. `on_quick_trade` — lines 4102 and 4110

**Location**: Inside `on_quick_trade`, inside the `try:` block.

**What changes**:

Line 4102 — replace:
```python
market_open, market_status = trading.is_market_open(config.SYMBOL)
```
with:
```python
market_open, market_status = self._broker.is_market_open(config.SYMBOL)
```

Lines 4110–4120 — replace `trading.apply_signal(` with `self._broker.apply_signal(`. All arguments stay identical.

**What must NOT change**: The surrounding `try/except` block, the `if not market_open:` guard, and the `update_last_action_ui(action_info)` call must stay untouched.

---

### 4. `bot_loop` — lines 8129 and 8173–8215

**Location**: Inside `bot_loop`, inside the outer `while` → inner `try:` block.

#### 4a. Line 8129 — `is_market_open`

Replace:
```python
market_open, market_status = trading.is_market_open(config.SYMBOL)
```
with:
```python
market_open, market_status = self._broker.is_market_open(config.SYMBOL)
```

#### 4b. Lines 8175–8178 — inline `_Adapter()` instantiation

Current code (lines 8175–8178):
```python
from src.broker.mt5_adapter import MT5BrokerAdapter as _Adapter
_broker = _Adapter()
account = _broker.get_account_info()
balance = account.balance if account is not None else 0.0
instrument_info = _broker.get_instrument_info(config.SYMBOL)
```

Replace with (remove the two `from ... import` / `_broker = _Adapter()` lines; use `self._broker`):
```python
account = self._broker.get_account_info()
balance = account.balance if account is not None else 0.0
instrument_info = self._broker.get_instrument_info(config.SYMBOL)
```

The `trading.calculate_dynamic_lot(atr_value, volume_ratio, instrument_info, balance)` call on line 8181 stays unchanged — this is a pure calculation, not a broker call.

#### 4c. Lines 8194 and 8205 — `apply_pyramid_signal` and `apply_signal`

Line 8194 — replace `trading.apply_pyramid_signal(` with `self._broker.apply_pyramid_signal(`. All arguments stay identical.

Line 8205 — replace `trading.apply_signal(` with `self._broker.apply_signal(`. All arguments stay identical.

**What must NOT change**: The `if pyramiding and atr_value > 0 and signal == "buy":` / `else:` branch structure, the `if action_info:` block that follows, and the `update_last_action_ui(action_info)` call.

---

## Invariant Checklist

- [x] No `chart.run_script()` from non-main-thread context — this change adds no JS calls
- [x] DOM elements use `getElementById` guard before creation — no DOM changes in this spec
- [x] New config accesses use `getattr(config, "KEY", default)` pattern — no new config accesses
- [x] New `self._broker` initialized in `__init__` before first use — placed after `_init_strategy_registry()`, before chart and any method that could call it
- [x] Strategy registry writes only from main thread — not touched by this spec
- [x] No new JS→Python handler — no handler name collision possible

---

## Call Sites NOT Migrated (intentional)

| Line | Call | Reason |
|------|------|--------|
| 6639 | `trading.decode_trade_comment(...)` | Pure string parser — not in IBrokerAdapter; stays on `trading` |
| 6654 | `trading.decode_trade_comment(...)` | Same |
| 7483 | `trading.decode_trade_comment(...)` | Same |
| 8181 | `trading.calculate_dynamic_lot(...)` | Pure math function — not in IBrokerAdapter; stays on `trading` |

These calls are documented explicitly so Felix does not migrate them by mistake.
