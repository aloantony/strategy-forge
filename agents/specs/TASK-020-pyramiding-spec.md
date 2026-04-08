# Pre-Implementation: Pyramiding — Detection and Execution

**By**: Daniel
**Date**: 2026-04-06
**Task**: TASK-020
**Status**: ready

---

## Formal Problem Statement

**Input**:
- `symbol`: str — MT5 symbol identifier (e.g. `#Germany40`)
- `magic_number`: int — unique per-strategy identifier used to tag and filter positions
- `atr_value`: float — ATR(14) value at `df.iloc[-2]`, passed from the strategy via its `get_last_signal_payload` return dict; must be > 0
- `lot`: float — position size in lots (from sizing layer — computed before this call for this sprint; see TASK-021 for dynamic sizing)
- `strategy_key`, `strategy_label`, `signal_reason`: str — metadata for trade comments
- Live MT5 context: current positions accessible via `mt5.positions_get(symbol=symbol)`, current ask price via `mt5.symbol_info_tick(symbol).ask`

**Output**:
- A result dict (same schema as `apply_signal()` return) with key `"actions"` containing the list of order results; or `None` if no entry was executed (pyramid threshold not met, or some guard rejected)

**Constraints**:
- Long-only: only BUY orders are opened; SELL direction is never considered here
- Each pyramid position is independent: its own SL and TP, each calculated from the ATR at the moment of that entry
- `apply_signal()` must NOT change behavior for strategies that do not set `pyramiding: True` in their payload — full backward compatibility required
- `_send_order()` must remain callable with its existing signature — new SL/TP parameters must be optional
- All positions opened by this strategy share the same `magic_number` — filtering is by magic_number only
- Thread safety: the caller (`run_bot_loop`) already holds `ORDER_EXECUTION_LOCK` when calling any trading function; no additional locking inside these functions
- `n` (positions) = 0–3 in typical live use; no performance concern on MT5 API calls at this scale

**Invariants**:
- `mt5.positions_get(symbol=symbol)` returns all open positions for the symbol; filtering by `magic == magic_number` gives only this strategy's positions
- `position.time` is the server-side open timestamp (int, seconds since epoch) — always monotonically increasing for independently opened positions; safe to use as recency key
- `position.price_open` is the exact fill price of each entry — available for all open positions
- `atr_value` > 0 (enforced by guard in the new function; if 0, abort)

**Clarity**: ✅ clear

---

## Candidate Algorithms

### 1. Embed pyramiding logic inside `apply_signal()`

- **Description**: Add an `atr_value` parameter (default 0) to `apply_signal()`. When non-zero and the strategy signals "buy" with existing BUY positions, check the pyramid threshold instead of doing nothing.
- **Time**: O(p) where p = number of open positions (MT5 API call + loop)
- **Space**: O(p)
- **Verdict**: eliminated
- **Reason**: Violates single-responsibility. `apply_signal()` is the framework's general-purpose signal executor used by all strategies; embedding pyramiding-specific business logic (ATR threshold, multi-position management) couples it to one strategy's behavior. Any future strategy with different pyramiding rules would require further branching. Also requires changing the public signature, which breaks the stated constraint of backward compatibility for all existing callers.

### 2. New function `apply_pyramid_signal()` in `trading.py`

- **Description**: A standalone peer function alongside `apply_signal()`. Encapsulates all pyramiding logic: fetch live positions, determine initial vs. pyramid entry, check price threshold, compute ATR-based SL/TP, and dispatch `_send_order()`. The execution layer (`run_bot_loop`) decides which function to call based on the payload flag.
- **Time**: O(p) for position lookup and linear scan to find max by time
- **Space**: O(p)
- **Verdict**: selected
- **Reason**: Clean separation of concerns. `apply_signal()` is unchanged. The pyramiding path is self-contained and testable in isolation. New pyramiding rules for a future strategy can be added without touching `apply_signal`. Callers that don't pass a `pyramiding` flag in payload never see this function. The `max()` call over p=0–3 positions is O(p) with negligible cost at 10s intervals.

### 3. Pyramiding detection in `run_bot_loop` before calling `apply_signal()`

- **Description**: `run_bot_loop` reads positions directly (calling `mt5.positions_get` itself), checks the threshold, and passes a modified signal or extra params to `apply_signal`.
- **Time**: O(p)
- **Space**: O(p)
- **Verdict**: eliminated
- **Reason**: `run_bot_loop` is in `main.py`, which is the bot orchestrator. Pulling MT5 position inspection and price comparison logic into `main.py` pushes execution concerns into the wrong layer. The trading module already owns position queries (`get_open_position_direction`, `get_position_info`, `_close_position`). Consistency demands the new function lives there. This also makes the trading logic untestable without running the full bot loop.

---

## Selected Algorithm

**Winner**: New function `apply_pyramid_signal()` (Algorithm 2)

**Justification**:
Given p=0–3 positions, called every ~10s under `ORDER_EXECUTION_LOCK` across up to 3 strategies:
- O(p) position lookup is negligible at this scale
- No algorithm choice meaningfully changes performance at p≤3 — the cost is the MT5 API call, not the Python loop
- The design constraint that eliminates Algorithm 1 (backward compatibility) and Algorithm 3 (layer separation) is architectural, not computational
- Trade-offs accepted: one additional MT5 API call per cycle per pyramiding strategy (to get fresh tick price inside `apply_pyramid_signal`). This is one `mt5.symbol_info_tick()` call — same as what `_send_order()` already does internally. No additional overhead vs. what we'd pay anyway.

---

## Pseudocode Spec

### Part 1 — New function: `get_all_positions(symbol, magic_number) -> list[dict]`

Replaces the need to extend `get_position_info()` (which is kept unchanged for backward compat).

```
function get_all_positions(symbol: str, magic_number: int) -> list[dict]:
    # Returns all open positions for this symbol+magic_number, sorted by time_open ascending.
    # Returns empty list if none.

    raw_positions = mt5.positions_get(symbol=symbol)
    if raw_positions is None or len(raw_positions) == 0:
        return []

    result = []
    for position in raw_positions:
        if position.magic != magic_number:
            continue
        result.append({
            "ticket":        position.ticket,
            "type":          "BUY" if position.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume":        position.volume,
            "price_open":    position.price_open,
            "price_current": position.price_current,
            "profit":        position.profit,
            "sl":            position.sl,
            "tp":            position.tp,
            "time_open":     position.time,   # int, seconds since epoch
        })

    # Sort ascending by open time so [-1] is the most recent
    result.sort(key=lambda p: p["time_open"])
    return result
```

---

### Part 2 — Extension to `_send_order()`: optional absolute SL/TP

Add two optional keyword parameters. All existing callers continue to work unchanged since both default to 0.

```
function _send_order(
    symbol,
    direction,
    lot,
    sl_points,         # existing — used if sl_price == 0
    tp_points,         # existing — used if tp_price == 0
    magic_number,
    order_comment = "",
    sl_price = 0.0,    # NEW: if > 0, use this absolute price as SL instead of sl_points
    tp_price = 0.0,    # NEW: if > 0, use this absolute price as TP instead of tp_points
):
    symbol_info = mt5.symbol_info(symbol)
    # ... existing symbol_info None guard unchanged ...

    point = symbol_info.point
    tick = mt5.symbol_info_tick(symbol)
    ask = tick.ask if tick else 0.0
    bid = tick.bid if tick else 0.0

    if direction == 1:   # BUY
        price = ask
        if sl_price > 0:
            sl = sl_price          # USE ABSOLUTE
        elif sl_points > 0:
            sl = price - (sl_points * point)
        else:
            sl = 0
        if tp_price > 0:
            tp = tp_price          # USE ABSOLUTE
        elif tp_points > 0:
            tp = price + (tp_points * point)
        else:
            tp = 0
        order_type = mt5.ORDER_TYPE_BUY

    elif direction == -1:  # SELL (unchanged logic, sl_price/tp_price not used for sells in this strategy)
        price = bid
        if sl_price > 0:
            sl = sl_price
        elif sl_points > 0:
            sl = price + (sl_points * point)
        else:
            sl = 0
        if tp_price > 0:
            tp = tp_price
        elif tp_points > 0:
            tp = price - (tp_points * point)
        else:
            tp = 0
        order_type = mt5.ORDER_TYPE_SELL

    # ... rest of function unchanged: normalize_volume, adjust_stops, filling retry, result dict ...
```

**Note**: `adjust_stops()` still runs after the sl/tp assignment — it enforces broker minimum stop distances. If the ATR-based SL is too close to the entry price (unusual for a DAX CFD with ATR typically 30–100 points), the broker stop floor will push it out and log a note in the result dict. This is correct behavior — we never want to send an order with an illegal stop distance.

---

### Part 3 — New function: `apply_pyramid_signal()` in `trading.py`

```
function apply_pyramid_signal(
    symbol: str,
    magic_number: int,
    atr_value: float,
    lot: float,
    strategy_key: str = "",
    strategy_label: str = "",
    signal_reason: str = "",
) -> dict | None:
    # Guard: reject if ATR is zero or negative (data error)
    if atr_value <= 0:
        return None

    # Get live ask price for threshold comparison and SL/TP calculation
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    ask = tick.ask
    if ask <= 0:
        return None

    # Get all current positions for this strategy
    positions = get_all_positions(symbol, magic_number)

    # Compute SL/TP for a hypothetical entry at current ask
    sl_price = ask - (1.0 * atr_value)
    tp_price = ask + (2.0 * atr_value)

    open_comment = build_trade_comment(
        strategy_key=strategy_key,
        signal_reason=signal_reason,
        action_kind="open"
    )

    if len(positions) == 0:
        # No existing position — this is the initial entry
        result = _send_order(
            symbol, 1, lot, 0, 0, magic_number,
            order_comment=open_comment,
            sl_price=sl_price,
            tp_price=tp_price,
        )
        actions = [result] if result else []
    else:
        # Existing positions — check pyramid threshold
        # The most recent entry is positions[-1] (sorted ascending by time_open)
        most_recent = positions[-1]

        # Safety: only pyramid onto BUY positions (long-only strategy)
        if most_recent["type"] != "BUY":
            return None

        last_entry_price = most_recent["price_open"]
        pyramid_threshold = last_entry_price + (0.5 * atr_value)

        if ask < pyramid_threshold:
            # Price has not advanced enough — do nothing this cycle
            return None

        # Threshold met — open pyramid entry
        result = _send_order(
            symbol, 1, lot, 0, 0, magic_number,
            order_comment=open_comment,
            sl_price=sl_price,
            tp_price=tp_price,
        )
        actions = [result] if result else []

    # Filter out None actions and return in same schema as apply_signal
    actions = [a for a in actions if a]
    if not actions:
        return None
    if not any(isinstance(a, dict) and a.get("success") is True for a in actions):
        return None

    return {
        "timestamp":     datetime.now(),
        "symbol":        symbol,
        "signal":        "buy",
        "strategy":      strategy_key,
        "strategy_label": strategy_label,
        "signal_reason": signal_reason,
        "pyramid":       True,            # distinguishes from normal apply_signal result
        "actions":       actions,
    }
```

---

### Part 4 — Extension to `_normalize_signal_payload()` in `main.py`

Add pass-through of two new fields from the strategy payload. All existing code paths are unchanged — both fields default to safe values.

```
function _normalize_signal_payload(value) -> dict:
    # ... existing logic unchanged for signal and reason extraction ...

    pyramiding = False
    atr_value = 0.0

    if isinstance(value, dict):
        pyramiding_raw = value.get("pyramiding", False)
        pyramiding = bool(pyramiding_raw) if pyramiding_raw is not None else False

        atr_raw = value.get("atr_value", 0.0)
        try:
            atr_value = float(atr_raw) if atr_raw is not None else 0.0
        except (TypeError, ValueError):
            atr_value = 0.0

    return {
        "signal":    _normalize_signal(signal_raw),   # unchanged
        "reason":    reason,                           # unchanged
        "pyramiding": pyramiding,                      # NEW
        "atr_value": atr_value,                        # NEW
    }
```

---

### Part 5 — Changes to `run_bot_loop()` in `main.py`

The execution decision point changes. Find the block that calls `trading.apply_signal(...)` and replace it:

```
# BEFORE (current code):
with ORDER_EXECUTION_LOCK:
    trading.apply_signal(
        config.SYMBOL, signal, config.LOT,
        config.SL_POINTS, config.TP_POINTS,
        entry["magic_number"],
        strategy_key=entry["key"],
        strategy_label=entry["label"],
        signal_reason=reason,
    )

# AFTER:
pyramiding = result.get("pyramiding", False)
atr_value  = result.get("atr_value", 0.0)

with ORDER_EXECUTION_LOCK:
    if pyramiding and atr_value > 0 and signal == "buy":
        trading.apply_pyramid_signal(
            config.SYMBOL,
            entry["magic_number"],
            atr_value,
            config.LOT,
            strategy_key=entry["key"],
            strategy_label=entry["label"],
            signal_reason=reason,
        )
    else:
        trading.apply_signal(
            config.SYMBOL, signal, config.LOT,
            config.SL_POINTS, config.TP_POINTS,
            entry["magic_number"],
            strategy_key=entry["key"],
            strategy_label=entry["label"],
            signal_reason=reason,
        )
```

**Note on `config.LOT` usage**: For this sprint, `apply_pyramid_signal` still uses `config.LOT` as the lot size, consistent with the current framework. TASK-021 (dynamic sizing) will replace this with a calculated lot passed in the same execution block. The interface is already compatible — `lot` is a parameter.

---

### Part 6 — Strategy payload contract (for Felix / TASK-025)

The strategy's `get_last_signal_payload()` must return this dict shape when the pyramiding condition is active:

```python
{
    "signal":    "buy",          # or "none"
    "reason":    "ADX>25 +DI cross",
    "pyramiding": True,          # tells execution layer to use apply_pyramid_signal
    "atr_value": <float>,        # df.iloc[-2]["atr_14"] — current ATR(14) value
}
```

When the signal is "none" (no trigger), `pyramiding` and `atr_value` may be omitted or set to False/0 — the execution layer will ignore them.

The strategy NEVER decides whether to pyramid or not — it always returns `pyramiding: True` when the ADX+DI trigger is active. The decision of initial vs. pyramid entry, and whether the threshold is met, is made entirely in `apply_pyramid_signal()`.

---

## Key Design Decisions Log

| Decision | Options considered | Winner | Reason |
|----------|--------------------|--------|--------|
| How to extend apply_signal | Modify apply_signal / new peer function / detect in run_bot_loop | New `apply_pyramid_signal()` | Backward compat + separation of concerns |
| How strategy passes ATR | From df column directly / via `get_last_signal_payload` field / strategy computes externally | Via payload field `"atr_value"` | Explicit, flexible, no implicit column name coupling in main.py |
| How strategy signals pyramiding intent | Special signal string / payload flag / always-on | Payload flag `"pyramiding": True` | Backward compat; existing strategies not affected |
| How to identify most recent position | By `price_open` max / by `time` (open timestamp) | `time` (open timestamp) | `time` is always strictly monotonic; `price_open` could be non-monotonic during pullback entries |
| SL/TP absolute vs points | Separate function / optional params on `_send_order` | Optional `sl_price`, `tp_price` params on `_send_order` | Minimal change; existing callers unaffected; `adjust_stops` still enforces broker floor |
| Where does `_close_position` behavior change? | Unchanged | Unchanged | `_close_position` already closes ALL positions for magic_number — correct exit behavior for all pyramid positions at once |

---

## Edge Cases Felix Must Handle

1. **`atr_value == 0`**: Guard at top of `apply_pyramid_signal()` — return None immediately. Log nothing (caller checks return value).

2. **`tick is None` or `ask <= 0`**: Guard in `apply_pyramid_signal()` — return None. Same failure mode as existing `_send_order` when tick is unavailable.

3. **Pyramid entry fails (MT5 error)**: Return the result dict from `_send_order` with `success=False`. The result is included in `actions` but the `any(success=True)` guard will cause `apply_pyramid_signal` to return None — same behavior as `apply_signal`.

4. **Existing SELL positions under same magic_number**: Guard in the `len(positions) > 0` branch — if `most_recent["type"] != "BUY"`, return None without acting. This is a safety check; it should never occur for the long-only strategy.

5. **`adjust_stops` pushes ATR-based SL**: Acceptable. The broker floor wins. The result dict will log the adjustment note (existing behavior via `stops_note` in `_send_order`).

6. **Multiple pyramid entries in same cycle**: Not possible within a single execution path. The lock is held per `apply_pyramid_signal` call; each cycle processes strategies sequentially within the lock.

7. **`get_all_positions` returns no positions after positions existed**: Race condition with a stop-out or manual close. The empty list triggers the "initial entry" path — which is the correct behavior (re-enter if signal is still active).

---

## Files to Modify (for Felix — TASK-023)

| File | Change |
|------|--------|
| `trading.py` | Add `get_all_positions()` function (new, public) |
| `trading.py` | Add `sl_price=0.0`, `tp_price=0.0` optional params to `_send_order()` |
| `trading.py` | Add `apply_pyramid_signal()` function (new, public) |
| `main.py` | Extend `_normalize_signal_payload()` to pass through `pyramiding` and `atr_value` |
| `main.py` | Replace `apply_signal()` call in `run_bot_loop()` with the if/else branch |

**Do not modify**: `get_position_info()`, `get_open_position_direction()`, `_close_position()`, `apply_signal()`. All five existing trading functions are unchanged.
