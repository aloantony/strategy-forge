# Pre-Implementation: IBrokerAdapter Contract Audit — ExecutionEngine Decoupling

**By**: Daniel
**Date**: 2026-04-20
**Task**: TASK-053
**Status**: ready

---

## Formal Problem Statement

**Input**:
- `IBrokerAdapter` abstract class — `src/broker/interface.py`
- `MT5BrokerAdapter` concrete class — `src/broker/mt5_adapter.py`
- `ExecutionEngine` — `src/runtime/execution_engine.py`
- `trading.py` — private helpers `_send_order`, `_close_position`, and public `build_trade_comment`

**Output**: A written spec confirming whether `IBrokerAdapter` is complete, identifying every gap, specifying the MT5 API calls that replace private helper calls, and specifying the `build_trade_comment` relocation.

**Constraints**:
- No code modified in this task (spec only).
- `modify_tp` must be implemented this sprint (pre-decided).
- `build_trade_comment` and helpers move to `src/broker/comment.py`; `trading.py` re-exports (pre-decided).
- `decode_trade_comment` stays in `trading.py` — it is called by `gui_charts.py` via `trading.decode_trade_comment(...)` and is outside the broker abstraction layer.

**Invariants**:
- All `ExecutionEngine._execute_*` methods are already delegating to `self._broker`; no `trading._send_order` or `trading._close_position` calls remain inside `execution_engine.py`.
- `MT5BrokerAdapter.modify_sl` already calls `mt5.order_send` directly (no `trading.py` coupling) — pattern confirmed and reusable for `modify_tp` and for replacing `_send_order`/`_close_position`.

**Clarity**: clear

---

## Section 1 — IBrokerAdapter Completeness Audit

### Methods ExecutionEngine calls on `self._broker` today

| Call site (execution_engine.py) | Method signature called | Interface declares it? |
|---------------------------------|------------------------|------------------------|
| `_execute_open` (line 174) | `send_order(symbol, order_type, lot, magic, sl_price, tp_price, strategy_key, strategy_label, signal_reason) -> OrderResult` | Yes — matches exactly |
| `_execute_close` (line 267) | `close_position(symbol, magic, strategy_key, strategy_label, close_reason) -> bool` | Yes — matches exactly |
| `_execute_move_sl` (line 321) | `modify_sl(symbol, magic, new_sl_price) -> bool` | Yes — matches exactly |
| `_execute_move_tp` (line 333–337) | `modify_tp(symbol, magic, new_tp_price) -> bool` | **NO — not declared in IBrokerAdapter** |

**Finding**: The interface is **incomplete by one method**: `modify_tp` is absent from `IBrokerAdapter`. The method must be added.

`_execute_move_tp` currently returns `not_supported`. Once `modify_tp` is added to the interface and implemented in `MT5BrokerAdapter`, `_execute_move_tp` follows the identical pattern as `_execute_move_sl` (lines 311–331) — read `new_tp_price` from `resolved`, call `self._broker.modify_tp(...)`, map `bool` result to action status.

---

## Section 2 — modify_tp: Interface Signature and MT5 Implementation

### 2a. Method to add to IBrokerAdapter (`src/broker/interface.py`)

```
@abstractmethod
def modify_tp(
    self,
    symbol: str,
    magic: int,
    new_tp_price: float,
) -> bool:
    ...
```

Rationale: mirrors the exact signature of `modify_sl` — same parameter roles, same return semantics.

### 2b. MT5 API call for modify_tp

`mt5.order_send` with `TRADE_ACTION_SLTP` is the correct MT5 action for modifying SL and/or TP on an open position. This is confirmed by the existing `modify_sl` implementation in `MT5BrokerAdapter` (lines 64–83), which already uses this action successfully.

**Critical constraint — must read current SL before modifying TP**:
`TRADE_ACTION_SLTP` requires both `sl` and `tp` fields in the request. MT5 interprets a missing or zero `sl`/`tp` as "set to zero" (i.e., remove the stop). Therefore:
- When modifying TP only, the current SL must be read from the live position (`pos.sl`) and forwarded in the request unchanged.
- When modifying SL only (as `modify_sl` already does), the current TP is read from `pos.tp` and forwarded unchanged.

The existing `modify_sl` implementation already follows this pattern correctly (it preserves `pos.tp`). `modify_tp` must do the symmetric thing (preserve `pos.sl`).

### 2c. Pseudocode for MT5BrokerAdapter.modify_tp

```
function modify_tp(symbol: str, magic: int, new_tp_price: float) -> bool:
    # Reads all open positions for (symbol, magic), sends TRADE_ACTION_SLTP
    # preserving the current sl. Returns True if at least one position was modified.

    try:
        positions = mt5.positions_get(symbol=symbol) or []
        positions = [p for p in positions if p.magic == magic]
        success = False
        for pos in positions:
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": pos.ticket,
                "symbol": symbol,
                "sl": pos.sl,          # preserve current SL — do not zero it out
                "tp": new_tp_price,    # new TP value
                "magic": magic,
            }
            result = mt5.order_send(request)
            if result and result.retcode == TRADE_RETCODE_DONE:
                success = True
        return success
    except Exception:
        return False
```

---

## Section 3 — ExecutionEngine call → IBrokerAdapter mapping (complete)

### send_order

ExecutionEngine call (execution_engine.py line 174–184):
```
self._broker.send_order(
    symbol=symbol,
    order_type=order_type,    # int: 0=BUY, 1=SELL
    lot=volume,
    magic=self._magic,
    sl_price=sl_price,        # float or None
    tp_price=tp_price,        # float or None
    strategy_key=self._strategy_key,
    strategy_label=self._strategy_key,  # NOTE: passes strategy_key for both key and label
    signal_reason=reason,
)
```

IBrokerAdapter signature: matches exactly. No parameter name or type mismatch.

Note: `strategy_label` is passed `self._strategy_key` (not a distinct label value). This is intentional in the current implementation — the adapter ignores `strategy_label` beyond embedding it in the comment. No interface change needed.

Return type: `OrderResult` dataclass — `ExecutionEngine` reads `.success`, `.order_id`, `.deal_id`, `.retcode`, `.comment`, `.price`, `.volume`. All fields present in the current `OrderResult` definition.

### close_position

ExecutionEngine call (execution_engine.py line 267–273):
```
self._broker.close_position(
    symbol=symbol,
    magic=self._magic,
    strategy_key=self._strategy_key,
    strategy_label=self._strategy_key,
    close_reason=reason,
)
```

IBrokerAdapter signature: matches exactly. Return type `bool` — `ExecutionEngine` reads as `success` flag. No mismatch.

### modify_sl

ExecutionEngine call (execution_engine.py line 321–325):
```
self._broker.modify_sl(
    symbol=symbol,
    magic=self._magic,
    new_sl_price=new_sl,
)
```

IBrokerAdapter signature: matches exactly. Return type `bool`. No mismatch.

### modify_tp (to be added)

ExecutionEngine call (execution_engine.py line 333–337 — currently returns `not_supported`):
```
self._broker.modify_tp(
    symbol=symbol,
    magic=self._magic,
    new_tp_price=new_tp,   # read from norm_action["resolved"]["new_tp_price"]
)
```

Once implemented, `_execute_move_tp` follows `_execute_move_sl` verbatim with these substitutions:
- `"move_stop_loss"` → `"move_take_profit"`
- `resolved.get("new_sl_price")` → `resolved.get("new_tp_price")`
- `self._broker.modify_sl(...)` → `self._broker.modify_tp(...)`
- `new_sl_price` → `new_tp_price`
- Log message: `f"TP movido a {new_tp:.5f}"`

---

## Section 4 — What MT5BrokerAdapter.send_order and close_position should do

These two methods currently call private helpers from `trading.py`:
- `send_order` calls `trading._send_order()`
- `close_position` calls `trading._close_position()`

Both private helpers do MT5 API work that the adapter should own directly. After decoupling, the adapter must replicate that logic inline, calling MT5 directly. Below is the full behavioral spec.

### 4a. MT5BrokerAdapter.send_order — replacement logic

What `trading._send_order` does (trading.py lines 619–758) that must be replicated:
1. `mt5.symbol_info(symbol)` — get symbol metadata
2. `mt5.symbol_select(symbol, True)` if not visible
3. `mt5.symbol_info_tick(symbol)` — get current ask/bid
4. Compute `price`, `sl`, `tp` from direction + `sl_price`/`tp_price` (price-based) or `sl_points`/`tp_points` (points-based). The adapter always passes `sl_points=0, tp_points=0` and uses price-based inputs.
5. `normalize_volume(lot, symbol_info)` — clamp to symbol's min/max/step
6. `adjust_stops(direction, price, sl, tp, symbol_info, tick)` — enforce broker's min stop distance
7. `choose_filling_mode(symbol_info, ...)` — select fill type
8. Build and send via `order_send_with_filling_retry(request, symbol_info)` — automatic filling mode retry

After decoupling, `MT5BrokerAdapter.send_order` must call these helpers directly from `trading`:
- `trading.normalize_volume` (public helper)
- `trading.adjust_stops` (public helper)
- `trading.choose_filling_mode` (public helper)
- `trading.order_send_with_filling_retry` (public helper)

None of these are private (no leading `_`). The only call to eliminate is `trading._send_order` (private).

**Pseudocode for MT5BrokerAdapter.send_order (replacement)**:

```
function send_order(symbol, order_type, lot, magic, sl_price, tp_price,
                    strategy_key="", strategy_label="", signal_reason=""):

    direction = 1 if order_type == 0 else -1   # 0=BUY→1, 1=SELL→-1

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return OrderResult(success=False, retcode=-1, order_id="", deal_id="",
                           comment="symbol_info unavailable")

    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)

    tick = mt5.symbol_info_tick(symbol)
    ask  = tick.ask if tick else 0.0
    bid  = tick.bid if tick else 0.0

    if direction == 1:   # BUY
        price     = ask
        order_mt5 = mt5.ORDER_TYPE_BUY
    else:                # SELL
        price     = bid
        order_mt5 = mt5.ORDER_TYPE_SELL

    sl = sl_price or 0.0
    tp = tp_price or 0.0

    lot, volume_note = trading.normalize_volume(lot, symbol_info)
    if lot <= 0:
        return OrderResult(success=False, retcode=-1, order_id="", deal_id="",
                           comment=f"volume invalid: {volume_note}")

    sl, tp, _ = trading.adjust_stops(direction, price, sl, tp, symbol_info, tick)

    filling_mode = trading.choose_filling_mode(symbol_info)
    comment_str  = build_trade_comment(             # imported from src.broker.comment
        strategy_key=strategy_key,
        signal_reason=signal_reason,
        action_kind="open",
    )
    request_comment = comment_str or _DEFAULT_OPEN_COMMENT

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot,
        "type":         order_mt5,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    20,
        "magic":        magic,
        "comment":      request_comment,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }

    result, used_mode, tried_modes, last_error = trading.order_send_with_filling_retry(
        request, symbol_info
    )
    success = result is not None and result.retcode == TRADE_RETCODE_DONE

    return OrderResult(
        success  = success,
        retcode  = result.retcode if result else -1,
        order_id = str(getattr(result, "order", "") or ""),
        deal_id  = "",
        comment  = str(getattr(result, "comment", "") or ""),
        price    = price,
        volume   = lot,
    )
```

Note: `_DEFAULT_OPEN_COMMENT` ("Bot trading") and `TRADE_RETCODE_DONE = 10009` are already defined at module level in `mt5_adapter.py` (TRADE_RETCODE_DONE) and `trading.py` (_DEFAULT_OPEN_COMMENT). Alex must define `_DEFAULT_OPEN_COMMENT = "Bot trading"` in `mt5_adapter.py` (or import it from `src.broker.comment` if moved there — see Section 5 for the comment module scope decision).

### 4b. MT5BrokerAdapter.close_position — replacement logic

What `trading._close_position` does (trading.py lines 542–616) that must be replicated:
1. `mt5.positions_get(symbol=symbol)` — get open positions
2. `mt5.symbol_info(symbol)` — get symbol metadata for filling mode
3. `get_allowed_filling_modes` + `choose_filling_mode` — resolve filling
4. For each position matching `magic_number`: build a counter-order request and call `order_send_with_filling_retry`

After decoupling, `MT5BrokerAdapter.close_position` must call these helpers directly from `trading`:
- `trading.get_allowed_filling_modes` (public)
- `trading.choose_filling_mode` (public)
- `trading.order_send_with_filling_retry` (public)

The only call to eliminate is `trading._close_position` (private).

**Pseudocode for MT5BrokerAdapter.close_position (replacement)**:

```
function close_position(symbol, magic, strategy_key="", strategy_label="", close_reason=""):

    comment_str = build_trade_comment(              # imported from src.broker.comment
        strategy_key=strategy_key,
        signal_reason=close_reason,
        action_kind="close",
    )
    request_comment = comment_str or _DEFAULT_CLOSE_COMMENT

    positions = mt5.positions_get(symbol=symbol) or []
    positions = [p for p in positions if p.magic == magic]

    if not positions:
        return False

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return False

    filling_mode = trading.choose_filling_mode(symbol_info)

    any_success = False
    for pos in positions:
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       pos.volume,
            "type":         mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY
                            else mt5.ORDER_TYPE_BUY,
            "position":     pos.ticket,
            "deviation":    20,
            "magic":        magic,
            "comment":      request_comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }
        result, used_mode, tried, last_error = trading.order_send_with_filling_retry(
            request, symbol_info
        )
        if result and result.retcode == TRADE_RETCODE_DONE:
            any_success = True

    return any_success
```

Note: `_DEFAULT_CLOSE_COMMENT = "Cierre automatico"` — Alex must define this constant in `mt5_adapter.py`.

---

## Section 5 — build_trade_comment relocation to src/broker/comment.py

### 5a. Exact list of symbols to move from trading.py to src/broker/comment.py

All of these symbols are currently defined in `trading.py` and are used exclusively by `build_trade_comment` (or only internally within the comment-building subsystem):

| Symbol | Kind | Lines in trading.py |
|--------|------|---------------------|
| `_TRADE_COMMENT_PREFIX` | constant (`str`) | 23 |
| `_MT5_COMMENT_MAX_LEN` | constant (`int`) | 26 |
| `_STRATEGY_TOKEN_MAX_LEN` | constant (`int`) | 27 |
| `_REASON_TOKEN_MAX_LEN` | constant (`int`) | 28 |
| `_FALLBACK_OPEN_COMMENT` | constant (`str`) | 29 |
| `_FALLBACK_CLOSE_COMMENT` | constant (`str`) | 30 |
| `_sanitize_comment_token` | private function | 33–39 |
| `build_trade_comment` | public function | 94–134 |

**Symbols that must NOT move** (they have callers outside the comment subsystem):

| Symbol | Reason to keep in trading.py |
|--------|------------------------------|
| `_DEFAULT_OPEN_COMMENT` | Used by `_send_order` (trading.py line 717) |
| `_DEFAULT_CLOSE_COMMENT` | Used by `_close_position` (trading.py line 576) |
| `_is_invalid_comment_error` | Used by `order_send_with_filling_retry` (trading.py line 292) |
| `_fallback_comment_from_request` | Used by `order_send_with_filling_retry` (trading.py line 293) |
| `decode_trade_comment` | Called by `gui_charts.py` via `trading.decode_trade_comment(...)` (3 call sites); the GUI spec (TASK-038) explicitly keeps `trading.decode_trade_comment` unchanged |

`decode_trade_comment` uses `_TRADE_COMMENT_PREFIX` and `_humanize_reason_token`. After the move:
- `_TRADE_COMMENT_PREFIX` will live in `src/broker/comment.py`; `trading.py` must import it back for `decode_trade_comment` to use.
- `_humanize_reason_token` is used only by `decode_trade_comment` — it stays in `trading.py`.

### 5b. src/broker/comment.py — module contents

```
# src/broker/comment.py
# Comment-building helpers for MT5 order comments.
# Moved from trading.py per TASK-053/054.

import re

_TRADE_COMMENT_PREFIX    = "TA"
_MT5_COMMENT_MAX_LEN     = 31
_STRATEGY_TOKEN_MAX_LEN  = 10
_REASON_TOKEN_MAX_LEN    = 24
_FALLBACK_OPEN_COMMENT   = "TAOPEN"
_FALLBACK_CLOSE_COMMENT  = "TACLOSE"


def _sanitize_comment_token(value: str, max_len: int) -> str:
    # [identical body from trading.py]


def build_trade_comment(
    strategy_key: str = "",
    signal_reason: str = "",
    action_kind: str = "open"
) -> str:
    # [identical body from trading.py]
```

No other symbols belong in this module. `decode_trade_comment` stays in `trading.py`.

### 5c. trading.py changes

Remove the definitions of the 8 symbols listed in 5a. Add this shim immediately after the remaining constants block (around line 30), before `_is_invalid_comment_error`:

```python
# Moved to src.broker.comment — re-exported for backward compatibility
from src.broker.comment import (
    _TRADE_COMMENT_PREFIX,
    build_trade_comment,
)
```

Re-exporting `_TRADE_COMMENT_PREFIX` is necessary because `decode_trade_comment` (which stays in `trading.py`) uses it. Re-exporting `build_trade_comment` covers all callers that do `trading.build_trade_comment(...)` or `from trading import build_trade_comment` — they continue to work without modification.

Callers of `build_trade_comment` currently in `trading.py` itself (`apply_signal` lines 795/798, `apply_pyramid_signal` line 937) will use the re-exported name — no change needed in those call sites.

### 5d. MT5BrokerAdapter import change

In `src/broker/mt5_adapter.py`, replace the current `trading.build_trade_comment(...)` calls with a direct import:

```python
from src.broker.comment import build_trade_comment, _FALLBACK_OPEN_COMMENT, _FALLBACK_CLOSE_COMMENT
```

And call `build_trade_comment(...)` directly (not `trading.build_trade_comment(...)`). The `import trading` line stays because `send_order` and `close_position` still call public helpers (`trading.normalize_volume`, `trading.adjust_stops`, etc.) until TASK-054 completes the full inlining. After Section 4 changes are applied, the remaining `trading.*` calls in the adapter will be only the public helpers listed in Sections 4a/4b.

### 5e. External callers audit

The grep confirms no caller outside of `trading.py` and `MT5BrokerAdapter` imports `build_trade_comment` directly from `trading`. The re-export shim in `trading.py` is sufficient — no other files need updating.

`gui_charts.py` calls `trading.decode_trade_comment(...)` (3 sites) — this function stays in `trading.py` and is unaffected.

---

## Section 6 — ExecutionEngine._execute_move_tp pseudocode

This replaces the current stub (execution_engine.py lines 333–337):

```
function _execute_move_tp(norm_action: dict, plan_id: str, action_id: str) -> dict:
    symbol   = norm_action.get("symbol", self._symbol)
    resolved = norm_action.get("resolved", {})
    new_tp   = resolved.get("new_tp_price")

    if new_tp is None:
        return self._action_report(action_id, "move_take_profit", symbol,
                                   "rejected_technical",
                                   "No se pudo resolver el nuevo TP")

    try:
        success = self._broker.modify_tp(
            symbol=symbol,
            magic=self._magic,
            new_tp_price=new_tp,
        )
    except Exception as exc:
        return self._action_report(action_id, "move_take_profit", symbol,
                                   "error", str(exc))

    status = "executed" if success else "rejected_broker"
    msg    = f"TP movido a {new_tp:.5f}" if success else "Error moviendo TP"
    return self._action_report(action_id, "move_take_profit", symbol, status, msg)
```

---

## Notas / Ambigüedades

1. **`_DEFAULT_OPEN_COMMENT` and `_DEFAULT_CLOSE_COMMENT` scope**: These two constants appear in the "symbols to move" candidate list but are currently used by `trading._send_order` and `trading._close_position`. After TASK-054, those private helpers will be inlined into the adapter. At that point, the adapter will need these constants. The decision recorded here: they stay in `trading.py` for now (since `_send_order`/`_close_position` still exist there during TASK-054). Alex should define `_DEFAULT_OPEN_COMMENT = "Bot trading"` and `_DEFAULT_CLOSE_COMMENT = "Cierre automatico"` as module-level constants in `mt5_adapter.py` as part of TASK-054. A future cleanup task can remove them from `trading.py` once the private helpers are deleted.

2. **`strategy_label` parameter**: `ExecutionEngine` passes `strategy_key` for both `strategy_key` and `strategy_label` in `send_order` and `close_position`. This is an existing simplification. The interface correctly accepts both; the adapter currently ignores `strategy_label` (it only uses `strategy_key` for the comment). No change needed.

3. **`modify_tp` with positions that have no TP set** (`pos.tp == 0.0`): Setting `new_tp_price` on a position that has no TP is a valid operation — the adapter simply sends `tp=new_tp_price`. No guard needed. Conversely, a caller passing `new_tp_price=0.0` would remove the TP — this is MT5 semantics and is acceptable given that `ExecutionEngine` controls the value.

4. **`apply_signal` and `apply_pyramid_signal` in the adapter**: These two methods (adapter lines 85–110) continue to delegate to `trading.apply_signal` / `trading.apply_pyramid_signal`. They are not touched by this sprint — they are in the "high-level signals" section of the interface, separate from the execution path. TASK-055 will review them.
