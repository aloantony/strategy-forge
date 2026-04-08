# Pre-Implementation: Dynamic Sizing and Aggregate Risk Control

**By**: Daniel
**Date**: 2026-04-08
**Task**: TASK-021
**Status**: ready

---

## Formal Problem Statement

This task decomposes into two sub-problems that must be solved together: **(A) lot sizing** and **(B) aggregate risk verification**. Both are needed before any entry (initial or pyramid) is dispatched.

### Sub-problem A — Dynamic Lot Calculation

**Input**:
- `symbol`: str — MT5 symbol identifier
- `atr_value`: float — ATR(14) at `df.iloc[-2]`, from strategy payload; must be > 0
- `volume_ratio`: float — `df.iloc[-2]["volume_ratio_20"]` (`tick_volume / SMA(tick_volume, 20)`), from strategy payload; must be > 0
- MT5 live data: `mt5.account_info().balance` (account balance in account currency), `mt5.symbol_info(symbol)` (`trade_tick_size`, `trade_tick_value`)

**Output**: `float` — calculated lot size, pre-normalization. Caller must pass through `normalize_volume()` before sending to MT5.

**Constraints**:
- Use `balance` (not `equity`) throughout — closed decision from context.md
- Cap the risk-per-entry at 1% of balance (per-entry cap, not strategy-total — see §Selected Algorithm A)
- If any required MT5 data is unavailable or invalid, return 0.0 (caller treats as abort)
- Result is raw lot; normalization (`normalize_volume()`) is the caller's responsibility

**Invariants**:
- `atr_value` > 0 (guarded at call site)
- `volume_ratio` = `tick_volume_current / rolling_mean(tick_volume, 20)` — this is `volume_ratio_20` from the indicator catalogue; values typically in range [0.2, 3.0], occasionally higher on spikes
- `balance` > 0 for any live account (guarded)
- `trade_tick_value / trade_tick_size` > 0 for any valid CFD symbol

**Clarity**: ✅ clear

---

### Sub-problem B — Aggregate Risk Verification

**Input**:
- `symbol`: str
- `magic_number`: int
- `new_lot`: float — normalized lot for the entry being evaluated
- `atr_value`: float — ATR(14) at `df.iloc[-2]` — used to estimate the new entry's risk (SL = entry − 1×ATR)
- `balance`: float — account balance (already fetched by the sizing function)
- `positions`: list[dict] — already-fetched open positions (reuse from `apply_pyramid_signal` to avoid duplicate MT5 API call)
- MT5 live data: `mt5.symbol_info(symbol)` (`trade_tick_size`, `trade_tick_value`)

**Output**: `(allowed: bool, aggregate_risk_pct: float)` — whether adding this entry keeps the strategy under the 3% per-ticker aggregate risk limit, and what the total risk% would be after adding the new entry.

**Constraints**:
- Risk of each existing position is computed from `price_open - sl` (ATR-based SL set at open time)
- Positions with `sl == 0` are excluded from risk sum (no SL set — treated as unknown risk, not counted)
- The 3% limit uses `balance` as the denominator
- `get_all_positions()` is already called by `apply_pyramid_signal()` for the pyramiding logic — pass those results in to avoid a second MT5 API call

**Invariants**:
- All positions under `magic_number` are from the same strategy (closed decision from TASK-020)
- All open positions for this long-only strategy have `type == "BUY"` — SELL positions are ignored in the risk sum
- `price_open - sl > 0` for any BUY position with a valid SL (SL is below entry price)

**Clarity**: ✅ clear

---

## Candidate Algorithms — Sub-problem A (Lot Sizing)

### 1. Fixed lot — `config.LOT` (current approach)

- **Description**: Use the global constant regardless of market conditions or account size.
- **Time**: O(1), no external calls
- **Space**: O(1)
- **Verdict**: eliminated
- **Reason**: Does not implement the strategy's requirement. `primeraEstrategia.md` explicitly defines dynamic sizing as `(vol_ratio × 0.5%) × balance` with a 1% per-entry cap.

### 2. Risk-based position sizing (selected)

- **Description**: Determine a risk budget in money (`target_risk_pct × balance`), determine the money risked per 1 lot given the ATR-based SL distance, then divide to get the lot.
  - `target_risk_pct = min(volume_ratio × 0.005, 0.01)`
  - `risk_money = target_risk_pct × balance`
  - `risk_per_lot = atr_value × (trade_tick_value / trade_tick_size)`
  - `lot = risk_money / risk_per_lot`
- **Time**: O(1) — two MT5 property reads + arithmetic
- **Space**: O(1)
- **Verdict**: selected
- **Reason**: This is the standard "fixed fractional risk" sizing method and is the only interpretation consistent with the strategy spec. The formula directly encodes "risk at most X% of balance on this entry, where risk is defined as the monetary loss if SL is hit."

### 3. Percentage-of-notional sizing (`lot = pct × balance / (price × contract_size)`)

- **Description**: Size the position as a percentage of the account notional value (i.e., position value = pct × balance), ignoring the SL distance.
- **Time**: O(1)
- **Space**: O(1)
- **Verdict**: eliminated
- **Reason**: This approach sizes the position's notional value, not the risk. With a wide SL (large ATR) the actual monetary risk would exceed the intended percentage; with a tight SL it would be less. The strategy's formula is clearly risk-based (0.5% is a risk budget, SL defines the loss), not notional-based.

### Decision on volume_ratio vs. separate sma_volume_20 column

The task description asks whether to reuse `volume_ratio_<lookback>` from the indicator catalogue or define a new `sma_volume_20` column.

**Decision: reuse `volume_ratio_20`.**

`volume_ratio_20 = tick_volume / rolling_mean(tick_volume, 20)` — this IS the ratio `(tick_volume_actual / SMA_volumen_20)` from `primeraEstrategia.md`. The strategy's `prepare_dataframe` should add `volume_ratio_20` as an indicator (already in catalogue with period=20), and pass `df.iloc[-2]["volume_ratio_20"]` as the `volume_ratio` field in the payload. No new column type is needed.

### Decision on 1% cap scope: per-entry vs. strategy total

**Decision: per-entry cap.**

The strategy document states "Máximo riesgo por operación: 1%". "Operación" = a single trade/entry. Applying the cap per-entry is the correct interpretation. Applying it to the strategy total would make it redundant with the 3% aggregate limit for strategies with ≤3 entries, and would complicate the sizing function (it would need to inspect all open positions before computing the lot). The per-entry cap is a simple scalar clamp on `target_risk_pct` and needs no position inspection.

---

## Candidate Algorithms — Sub-problem B (Aggregate Risk)

### 1. Sum of SL-based monetary risk for all open positions + new entry (selected)

- **Description**: For each open BUY position, compute `risk_money = volume × (price_open − sl) × (tick_value / tick_size)`. Sum over all positions. Add the risk of the new entry: `new_lot × atr_value × (tick_value / tick_size)`. Compare total to `0.03 × balance`.
- **Time**: O(p) where p = open positions under magic_number (0–3)
- **Space**: O(1)
- **Verdict**: selected
- **Reason**: This is the standard risk management formula: worst-case monetary loss if all SLs are hit simultaneously. It is what the strategy intends by "riesgo agregado 3%". At p ≤ 3, the cost is negligible.

### 2. Sum of unrealized P&L of open positions

- **Description**: Use `position.profit` (current floating P&L) instead of `price_open − sl`.
- **Time**: O(p)
- **Space**: O(1)
- **Verdict**: eliminated
- **Reason**: Floating P&L is not risk. A position that is currently profitable has not reduced its maximum potential loss (its SL is still where it was set). This approach would undercount risk when positions are winning and overcount it when losing — neither is correct for a risk limit.

### 3. Notional value-based risk (lot × price × fixed_pct)

- **Description**: Estimate risk as a fixed percentage of position notional value.
- **Time**: O(1) — no position inspection needed
- **Space**: O(1)
- **Verdict**: eliminated
- **Reason**: Ignores actual SL placement. This would produce wildly different risk estimates for positions with tight vs. wide SLs, both having the same notional size. The strategy places SLs at ATR-based distances; we can and should use those actual SL prices.

---

## Selected Algorithms

### A — Lot Sizing

**Winner**: Risk-based position sizing (Algorithm 2)

**Justification**:
- `target_risk_pct = min(volume_ratio × 0.005, 0.01)` — encodes both the dynamic scaling and the 1% per-entry cap
- `lot = (target_risk_pct × balance) / (atr_value × tick_value / tick_size)` — standard fixed-fractional risk sizing
- At typical DAX values (ATR ≈ 50–100 points, tick_value/tick_size ≈ 1 €/point/lot, balance ≈ 10,000–50,000 €), this produces lots in the range 0.01–1.0 — within normal broker limits
- `normalize_volume()` handles all broker-specific constraints (min, max, step) after the calculation

### B — Aggregate Risk Verification

**Winner**: SL-based monetary risk sum (Algorithm 1)

**Justification**:
- `get_all_positions()` is already called by `apply_pyramid_signal()` — we pass those results in, eliminating a duplicate MT5 API call
- O(p) with p ≤ 3 is negligible at the 10s loop interval
- The SL-based formula accurately reflects committed risk (what we stand to lose if all stops are hit simultaneously), which is exactly the meaning of "riesgo agregado" in the strategy spec

---

## Pseudocode Spec

### Part 1 — New function: `calculate_dynamic_lot()` in `trading.py`

```
function calculate_dynamic_lot(
    symbol: str,
    atr_value: float,
    volume_ratio: float,
    balance: float = None,
) -> float:
    # Returns raw lot size (un-normalized). Caller must pass through normalize_volume().
    # Returns 0.0 on any data error — caller treats this as abort (fall back to config.LOT or skip entry).

    # Input guards
    if atr_value <= 0 or volume_ratio <= 0:
        return 0.0

    # Fetch balance if not provided
    if balance is None:
        account = mt5.account_info()
        if account is None:
            return 0.0
        balance = account.balance
    if balance <= 0:
        return 0.0

    # Fetch symbol info for monetary value conversion
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return 0.0

    tick_size = getattr(symbol_info, "trade_tick_size", 0.0) or 0.0
    tick_value = getattr(symbol_info, "trade_tick_value", 0.0) or 0.0
    if tick_size <= 0 or tick_value <= 0:
        return 0.0

    # Target risk% for this entry: dynamic ratio × 0.5%, capped at 1% per-entry
    target_risk_pct = min(volume_ratio * 0.005, 0.01)

    # Risk budget in account currency
    risk_money = target_risk_pct * balance

    # Money at risk per 1 lot if SL is hit (SL is placed at entry - 1×ATR)
    # Formula: ATR_distance × (tick_value / tick_size) = ATR distance expressed in account currency per lot
    risk_per_lot = atr_value * (tick_value / tick_size)
    if risk_per_lot <= 0:
        return 0.0

    lot = risk_money / risk_per_lot
    # Caller: pass lot through normalize_volume(lot, symbol_info) before use
    return lot
```

**Note on tick_value / tick_size**: This ratio is the monetary value per 1 price unit per 1 lot. For a DAX CFD (e.g. tick_size=0.01, tick_value=0.01), it equals 1 per unit, meaning ATR=50 → risk_per_lot=50 account units. For a forex pair (e.g. EURUSD with tick_size=0.00001, tick_value≈0.1 per lot of 100k), the formula still holds universally. Felix must not hardcode this ratio.

---

### Part 2 — New function: `check_aggregate_risk()` in `trading.py`

```
function check_aggregate_risk(
    symbol: str,
    new_lot: float,
    atr_value: float,
    balance: float,
    open_positions: list[dict],   # output of get_all_positions() — already fetched by caller
) -> (allowed: bool, aggregate_risk_pct: float):
    # Returns (True, total_risk_pct) if entry is allowed (total risk ≤ 3% of balance).
    # Returns (False, total_risk_pct) if adding this entry would breach the 3% limit.

    AGGREGATE_RISK_LIMIT = 0.03

    if balance <= 0:
        return (False, 0.0)

    # Fetch symbol info for monetary value conversion
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return (False, 0.0)

    tick_size = getattr(symbol_info, "trade_tick_size", 0.0) or 0.0
    tick_value = getattr(symbol_info, "trade_tick_value", 0.0) or 0.0
    if tick_size <= 0 or tick_value <= 0:
        return (False, 0.0)

    value_per_price_unit_per_lot = tick_value / tick_size

    # Risk of all existing open positions for this strategy
    existing_risk_money = 0.0
    for pos in open_positions:
        if pos["type"] != "BUY":
            continue   # safety: long-only strategy; ignore any non-BUY
        sl = pos["sl"]
        if sl <= 0:
            continue   # no SL set — cannot compute risk; skip (conservative choice: don't block)
        price_open = pos["price_open"]
        distance = price_open - sl
        if distance <= 0:
            continue   # malformed position data; skip
        pos_risk = pos["volume"] * distance * value_per_price_unit_per_lot
        existing_risk_money += pos_risk

    # Risk of the new entry (SL = entry - 1×ATR, so distance = atr_value)
    new_entry_risk = new_lot * atr_value * value_per_price_unit_per_lot

    total_risk_money = existing_risk_money + new_entry_risk
    aggregate_risk_pct = total_risk_money / balance

    allowed = aggregate_risk_pct <= AGGREGATE_RISK_LIMIT
    return (allowed, aggregate_risk_pct)
```

**Key design choice**: Positions with `sl == 0` are skipped rather than blocked. This is the conservative direction for risk management (not over-counting), and consistent with the constraint that this strategy always sets SLs — a `sl==0` position would indicate a data anomaly or a position opened by a different system under the same magic_number (which should not happen, but we handle it gracefully rather than aborting).

---

### Part 3 — Augmented `apply_pyramid_signal()` in `trading.py`

This extends the TASK-020 pseudocode for `apply_pyramid_signal()`. The changes are additions only; the pyramiding detection logic from TASK-020 is unchanged. New additions are marked with `# NEW`.

```
function apply_pyramid_signal(
    symbol: str,
    magic_number: int,
    atr_value: float,
    lot: float,                  # pre-computed by caller (calculate_dynamic_lot or config.LOT)
    strategy_key: str = "",
    strategy_label: str = "",
    signal_reason: str = "",
    balance: float = None,       # NEW: pre-fetched balance; if None, fetched here; passed to check_aggregate_risk
) -> dict | None:
    # Guard: reject if ATR is zero or negative
    if atr_value <= 0:
        return None

    # NEW: Fetch balance if not provided (needed for risk check)
    if balance is None:
        account = mt5.account_info()
        if account is None:
            return None
        balance = account.balance
    if balance <= 0:
        return None

    # Get live ask price
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    ask = tick.ask
    if ask <= 0:
        return None

    # Get all current positions (used for BOTH pyramiding logic AND risk check)
    positions = get_all_positions(symbol, magic_number)  # from TASK-020

    # Compute ATR-based SL/TP prices for a hypothetical entry at current ask
    sl_price = ask - (1.0 * atr_value)
    tp_price = ask + (2.0 * atr_value)

    open_comment = build_trade_comment(strategy_key=strategy_key, signal_reason=signal_reason, action_kind="open")

    if len(positions) == 0:
        # Initial entry path
        # NEW: Risk check before sending
        allowed, aggregate_risk_pct = check_aggregate_risk(
            symbol, lot, atr_value, balance, positions
        )
        if not allowed:
            return None   # entry rejected — aggregate risk would exceed 3%

        result = _send_order(symbol, 1, 0, 0, 0, magic_number,
                             order_comment=open_comment,
                             sl_price=sl_price, tp_price=tp_price)
        actions = [result] if result else []

    else:
        # Existing positions — check pyramid threshold (TASK-020 logic, unchanged)
        most_recent = positions[-1]   # sorted ascending by time_open; last = most recent

        if most_recent["type"] != "BUY":
            return None   # safety: non-BUY position under this magic_number

        last_entry_price = most_recent["price_open"]
        pyramid_threshold = last_entry_price + (0.5 * atr_value)

        if ask < pyramid_threshold:
            return None   # price has not advanced enough

        # NEW: Risk check before pyramid entry
        allowed, aggregate_risk_pct = check_aggregate_risk(
            symbol, lot, atr_value, balance, positions
        )
        if not allowed:
            return None   # pyramid entry rejected — aggregate risk would exceed 3%

        result = _send_order(symbol, 1, 0, 0, 0, magic_number,
                             order_comment=open_comment,
                             sl_price=sl_price, tp_price=tp_price)
        actions = [result] if result else []

    # Return result in same schema as apply_signal (TASK-020 logic, unchanged)
    actions = [a for a in actions if a]
    if not actions:
        return None
    if not any(isinstance(a, dict) and a.get("success") is True for a in actions):
        return None

    return {
        "timestamp":      datetime.now(),
        "symbol":         symbol,
        "signal":         "buy",
        "strategy":       strategy_key,
        "strategy_label": strategy_label,
        "signal_reason":  signal_reason,
        "pyramid":        True,
        "actions":        actions,
    }
```

**Note on `sl_points=0`**: `_send_order()` is called with `sl_points=0` and `tp_points=0` because `sl_price` and `tp_price` are set via the optional absolute-price parameters added in TASK-020. The `if sl_price > 0` branch inside `_send_order()` takes precedence. This is consistent with the TASK-020 spec.

---

### Part 4 — Extension to `_normalize_signal_payload()` in `main.py`

Add two new fields alongside the TASK-020 additions (`pyramiding`, `atr_value`).

```
function _normalize_signal_payload(value) -> dict:
    # ... existing logic for signal, reason, pyramiding, atr_value unchanged (TASK-020) ...

    dynamic_sizing = False
    volume_ratio = 0.0

    if isinstance(value, dict):
        dynamic_sizing_raw = value.get("dynamic_sizing", False)
        dynamic_sizing = bool(dynamic_sizing_raw) if dynamic_sizing_raw is not None else False

        volume_ratio_raw = value.get("volume_ratio", 0.0)
        try:
            volume_ratio = float(volume_ratio_raw) if volume_ratio_raw is not None else 0.0
        except (TypeError, ValueError):
            volume_ratio = 0.0

    return {
        "signal":         ...,    # unchanged
        "reason":         ...,    # unchanged
        "pyramiding":     ...,    # from TASK-020
        "atr_value":      ...,    # from TASK-020
        "dynamic_sizing": dynamic_sizing,   # NEW
        "volume_ratio":   volume_ratio,     # NEW
    }
```

---

### Part 5 — Updated dispatch block in `run_bot_loop()` in `main.py`

This replaces the TASK-020 dispatch block with the addition of dynamic sizing. The pyramiding decision and the apply_signal fallback from TASK-020 are preserved unchanged.

```
# In run_bot_loop(), inside the strategy result processing:

pyramiding     = result.get("pyramiding", False)
atr_value      = result.get("atr_value", 0.0)
dynamic_sizing = result.get("dynamic_sizing", False)   # NEW
volume_ratio   = result.get("volume_ratio", 0.0)       # NEW

with ORDER_EXECUTION_LOCK:
    if pyramiding and atr_value > 0 and signal == "buy":
        # Dynamic sizing path (NEW): compute lot before calling apply_pyramid_signal
        if dynamic_sizing and volume_ratio > 0 and atr_value > 0:
            account = mt5.account_info()
            balance = account.balance if account is not None else 0.0
            raw_lot = trading.calculate_dynamic_lot(
                config.SYMBOL, atr_value, volume_ratio, balance=balance
            )
            # normalize_volume needs symbol_info; let trading.calculate_dynamic_lot
            # return raw lot and we normalize here, or we can normalize inside
            # _send_order's path. For clarity: apply_pyramid_signal will pass the
            # raw_lot through normalize_volume internally (see _send_order).
            # So pass raw_lot directly — normalize_volume in _send_order handles it.
            lot = raw_lot if raw_lot > 0 else config.LOT  # fallback if sizing fails
        else:
            lot = config.LOT
            balance = None   # apply_pyramid_signal will fetch it

        trading.apply_pyramid_signal(
            config.SYMBOL,
            entry["magic_number"],
            atr_value,
            lot,
            strategy_key=entry["key"],
            strategy_label=entry["label"],
            signal_reason=reason,
            balance=balance if dynamic_sizing else None,
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

**Note on balance fetching**: When `dynamic_sizing=True`, we fetch `account.balance` once in `run_bot_loop` and pass it to both `calculate_dynamic_lot()` and `apply_pyramid_signal()` (which passes it to `check_aggregate_risk()`). This avoids two separate `mt5.account_info()` calls in the same lock-protected block for the same cycle. When `dynamic_sizing=False`, `balance=None` is passed and `apply_pyramid_signal()` fetches it internally (only needed for the risk check — which still runs even without dynamic sizing, using `config.LOT` as the lot).

---

### Part 6 — Strategy payload contract extension (for Felix / TASK-025)

The strategy's `get_last_signal_payload()` must return this complete dict shape (extending the TASK-020 payload):

```python
{
    "signal":         "buy",               # or "none"
    "reason":         "ADX>25 +DI cross",
    "pyramiding":     True,                # from TASK-020 — tells execution layer to use apply_pyramid_signal
    "atr_value":      <float>,             # from TASK-020 — df.iloc[-2]["atr_14"]
    "dynamic_sizing": True,                # NEW — tells execution layer to compute lot via calculate_dynamic_lot
    "volume_ratio":   <float>,             # NEW — df.iloc[-2]["volume_ratio_20"]
}
```

When the signal is "none": `pyramiding`, `atr_value`, `dynamic_sizing`, and `volume_ratio` may be omitted or set to False/0 — the execution layer discards them.

The strategy never decides what lot size to use — it only supplies the parameters needed for the execution layer to compute it. The execution layer is the single point of responsibility for sizing and risk decisions.

---

## Key Design Decisions Log

| Decision | Options considered | Winner | Reason |
|----------|--------------------|--------|--------|
| volume_ratio vs. sma_volume_20 separate column | New `sma_volume_20` column / reuse `volume_ratio_<lookback>` | Reuse `volume_ratio_20` | They are the same ratio; no new column type needed; already in catalogue |
| 1% cap scope | Per-entry cap / strategy-total cap | Per-entry | "Máximo riesgo por operación" = per entry; per-strategy cap would be redundant with the 3% aggregate limit |
| Where to compute lot | Inside `apply_pyramid_signal` / in `run_bot_loop` before calling | In `run_bot_loop` | Keeps `apply_pyramid_signal` focused on order dispatch + risk check; allows calling `calculate_dynamic_lot` independently for future non-pyramid strategies |
| Where to check aggregate risk | Inside `apply_pyramid_signal` (before `_send_order`) / in `run_bot_loop` before calling | Inside `apply_pyramid_signal` | Risk check is co-located with order dispatch (the gate before the actual send); positions are already fetched there; no need to duplicate the position fetch in `run_bot_loop` |
| Positions with sl==0 | Treat as infinite risk (block) / skip (don't count) / block if any exist | Skip (don't count) | These are anomalies (not expected for this strategy); blocking on them would cause false positives; not counting them is the safe direction (conservative risk undercount, not overcount) |
| Balance fetch: once or twice | Fetch once in run_bot_loop and pass down / fetch independently in calculate_dynamic_lot and apply_pyramid_signal | Once in run_bot_loop when dynamic_sizing=True | Avoids two `mt5.account_info()` calls in the same lock-protected block; consistent view of balance for both sizing and risk check |
| Fallback when calculate_dynamic_lot returns 0 | Abort entry / use config.LOT | Use config.LOT | A sizing failure (missing account info, invalid symbol data) should not silently block all entries; falling back to fixed lot maintains bot liveness; failure is logged via the returned 0.0 |

---

## Precision and Numerical Edge Cases

Felix must handle all of these:

1. **`lot` rounds to `volume_min` after `normalize_volume()`**: This happens when the account balance is small or the ATR is large. The actual risk % may be higher than intended (because you're forced to trade at the minimum lot size). This is acceptable behavior — document in the result dict's `volume_note` (already done by `normalize_volume()`). Do NOT abort.

2. **`risk_per_lot` is extremely small**: If `tick_value / tick_size` is very small and `atr_value` is very small, `lot` could overflow to an enormous number. Guard: if `lot > volume_max` after normalization, `normalize_volume()` will clamp it. This is already handled.

3. **`volume_ratio` spike (>> 3.0)**: On high-volume candles, `volume_ratio` could be 5–10×. The 1% per-entry cap (`min(..., 0.01)`) prevents this from producing an overlarge lot. The cap is the primary protection.

4. **`balance` changes between the fetch and `_send_order`**: This is a fundamental race condition in live trading; there is no practical mitigation within a single lock-protected execution block. The 10s loop interval is short enough that balance drift between fetch and order is negligible.

5. **`trade_tick_size` or `trade_tick_value` is None in SymbolInfo**: Use `getattr(..., 0.0)` and guard `<= 0`. Return 0.0 (abort sizing). This can happen for unusual symbols or if the broker's symbol data is incomplete.

6. **Position's `price_open - sl` is negative** (malformed position): Guard `distance = max(price_open - sl, 0)` — but actually use `if distance <= 0: continue` to skip the position entirely (a negative distance is a data error, not a hedging scenario for this long-only strategy).

7. **Integer vs. float lot arithmetic**: Python 3 float division is used throughout. No integer division risks. Round `atr_value / tick_size` is a float; no integer truncation.

---

## Files to Modify (for Felix — TASK-024)

| File | Change |
|------|--------|
| `trading.py` | Add `calculate_dynamic_lot(symbol, atr_value, volume_ratio, balance=None) -> float` (new public function) |
| `trading.py` | Add `check_aggregate_risk(symbol, new_lot, atr_value, balance, open_positions) -> (bool, float)` (new public function) |
| `trading.py` | Augment `apply_pyramid_signal()`: add `balance=None` parameter; call `check_aggregate_risk()` before each `_send_order()` call |
| `main.py` | Extend `_normalize_signal_payload()`: add extraction of `dynamic_sizing` (bool) and `volume_ratio` (float) |
| `main.py` | Update dispatch block in `run_bot_loop()`: add dynamic lot computation before `apply_pyramid_signal()` call; pass `balance` down |

**Do not modify**: `apply_signal()`, `get_position_info()`, `get_open_position_direction()`, `_close_position()`, `get_all_positions()`, `_send_order()` (the TASK-020 extension of `_send_order` with optional `sl_price`/`tp_price` params is unchanged).

---

## Interaction with TASK-020 Spec

TASK-021 is additive to TASK-020. No TASK-020 pseudocode is overridden; only `apply_pyramid_signal()` is augmented (two new `check_aggregate_risk` call sites added). The `lot` parameter source changes from `config.LOT` (TASK-020 placeholder) to `calculate_dynamic_lot()` output (TASK-021). Felix must implement TASK-023 (TASK-020 spec) first, then apply TASK-024 (TASK-021 spec) on top.

---

## Strategy-Side Requirements (for Felix — TASK-025)

The strategy `strategy_primera_estrategia.py` must:

1. Add `volume_ratio_20` to its indicator set in `prepare_dataframe`. This uses the existing `volume_ratio_<lookback>` pattern from the catalogue (period=20).

2. Return `"volume_ratio_20"` field in `get_last_signal_payload`:
   ```python
   "volume_ratio": df.iloc[-2]["volume_ratio_20"],
   "dynamic_sizing": True,
   ```

3. ATR-based fields (already required by TASK-020): `"atr_value": df.iloc[-2]["atr_14"]`.

No other changes to the strategy interface are required. The strategy remains isolated — it reads from `df` and returns a dict. All sizing and risk calculations happen in the execution layer.
