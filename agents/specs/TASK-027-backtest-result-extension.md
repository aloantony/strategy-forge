# Pre-Implementation: BacktestEngine result extension

**By**: Daniel
**Date**: 2026-04-11
**Task**: TASK-027
**Status**: ready

---

## Formal Problem Statement

**Input**:
- `BacktestEngine` instance after `run()` completes, with:
  - `self.equity_curve`: `list[{"time": int (epoch UTC), "equity": float, "balance": float}]` — one entry per visible candle
  - `self.closed_trades`: `list[dict]` — each trade with `profit: float`
  - `self.initial_balance: float`
  - `self.balance: float` (final)
  - `self.max_drawdown: float`
- `BacktestRequest` fields: all existing + three new cost params (see Part B)

**Output**: `dict` returned by `_build_success_result()` — JSON-serializable, consumed by `gui_charts.py` via `json.dumps` and `window.renderBacktestPanel(payload)`

**Constraints**:
- All new fields must be JSON-native types: `int`, `float`, `str`, `list`, `dict`. No `datetime`, `pd.Timestamp`, `np.float64`, etc.
- `equity_curve` size: 1 point per visible candle — M1/1yr ≈ 250 000 points; H1/1yr ≈ 6 000 points. No downsampling (DECISIÓN CERRADA 2026-04-11).
- `_build_success_result` is called once per backtest run, not on the hot path. O(n) passes are acceptable.
- `_mark_equity` is called once per visible candle on the hot path. No additional allocations beyond what already happen.

**Invariants**:
- `equity_curve` is sorted ascending by `time` (loop order guarantees this)
- All `equity_curve[i]["time"]` are `int` (epoch UTC) — already produced by `_time_to_epoch`
- `closed_trades[i]["profit"]` is `float` (positive = win, negative = loss, zero = breakeven)
- `initial_balance > 0` (enforced by `from_dict`)

**Clarity**: ✅ clear

---

## Part A — Fields to add to `_build_success_result`

### A1. `equity_curve`

Expose `self.equity_curve` verbatim. Already fully built during execution.

```
Field: "equity_curve"
Type:  list[dict]
Each entry: {"time": int, "equity": float, "balance": float}
```

No transformation needed. Reference the existing list directly.

### A2. `drawdown_curve`

Derived in `_build_success_result` via one O(n) pass over `self.equity_curve`.

```
Field: "drawdown_curve"
Type:  list[dict]
Each entry: {"time": int, "drawdown_pct": float}
```

`drawdown_pct` is the percentage decline from the running peak at each point:
```
drawdown_pct[i] = max(0, (running_peak - equity[i]) / running_peak * 100)
```

**Why derive in `_build_success_result` and not track in `_mark_equity`**:
- `_mark_equity` already updates `self.peak_equity` for `_update_drawdown`, but adding a second list to maintain there would bloat the hot-path method with result-assembly concerns.
- `_build_success_result` is the single place for all result construction. A single O(n) pass over a pre-built Python list is the correct abstraction boundary.
- At n=250k, a pass takes ~25ms — negligible relative to the backtest loop itself.

**Candidate algorithms considered**:

1. **Track in `_mark_equity` (per-candle)**
   - Time: O(1) per candle, O(n) total
   - Space: O(n) second list
   - Eliminated: couples result assembly to the hot-path method; `self.peak_equity` is already the right peak but the drawdown_curve list adds allocation on every candle

2. **Single pass in `_build_success_result` (selected)**
   - Time: O(n) one-shot
   - Space: O(n) output list, no per-candle allocation during run
   - Selected: clean separation — execution methods accumulate raw data; result method transforms it

### A3. Additional metrics

All computed in one O(n) pass over `self.closed_trades`:

| Field | Type | Formula |
|-------|------|---------|
| `profit_factor` | float | `gross_wins / gross_losses` (0.0 if no losses) |
| `avg_win` | float | `gross_wins / winning_trades` (0.0 if no wins) |
| `avg_loss` | float | `gross_losses / losing_trades` (0.0 if no losses; expressed as positive number) |
| `expectancy` | float | `win_rate_pct/100 * avg_win - loss_rate_pct/100 * avg_loss` |

Where:
- `gross_wins = sum(t["profit"] for t in closed_trades if t["profit"] > 0)`
- `gross_losses = sum(-t["profit"] for t in closed_trades if t["profit"] < 0)` (positive)

All four metrics are included. Justification:
- `profit_factor` separates genuinely profitable strategies from lucky ones (e.g., 70% win rate with tiny wins and huge losses still has PF < 1)
- `avg_win` / `avg_loss` are the components needed to audit expectancy
- `expectancy` is the single most interpretable per-trade summary metric for a trader

---

## Part B — Cost parameters in `BacktestRequest`

### B1. New fields on `BacktestRequest` dataclass

```python
spread_points: float = 0.0
slippage_points: float = 0.0
commission_per_lot: float = 0.0
```

### B2. Extension to `BacktestRequest.from_dict`

```
spread_points   = float(raw.get("spread_points") or 0.0)
slippage_points = float(raw.get("slippage_points") or 0.0)
commission_per_lot = float(raw.get("commission_per_lot") or 0.0)
```

### B3. Application during simulation

**Entry cost** (spread + slippage, direction-unfavorable):

```
entry_cost_points = (request.spread_points + request.slippage_points) * self.point
if direction == 1 (BUY):
    fill_price = raw_fill_price + entry_cost_points
if direction == -1 (SELL):
    fill_price = raw_fill_price - entry_cost_points
```

Applied in `_apply_standard_signal` and `_open_advanced_buy` before calling `_new_position`.

**Commission** (deducted from balance at open and at close):

```
# At open (in _apply_standard_signal and _open_advanced_buy, after fill_price is computed):
self.balance -= self.request.commission_per_lot * lot

# At close (in _close_position, after adding profit to balance):
self.balance -= self.request.commission_per_lot * position["volume"]
```

### B4. `cost_params` in result

```python
"cost_params": {
    "spread_points": self.request.spread_points,       # float
    "slippage_points": self.request.slippage_points,   # float
    "commission_per_lot": self.request.commission_per_lot,  # float
}
```

---

## Part C — Remove hardcoded indicators from `_build_market_dataframe`

Lines 88–102 of `backtesting/runtime.py` call three indicator functions unconditionally:

```python
# DELETE these three lines:
df = data_feed.add_baseline_bands(df, ...)
df = data_feed.add_supertrend(df, ...)
df = data_feed.add_tci(df, ...)
```

After deletion, `_build_market_dataframe` returns a DataFrame with exactly:

**Guaranteed columns delivered by the engine to every strategy:**
- `time` — UTC datetime (pd.Timestamp, UTC-aware)
- `open`, `high`, `low`, `close` — OHLCV prices (float)
- `tick_volume` (or `volume`) — as returned by MT5/provider
- `OHLC4`, `HLC3`, `HL2`, `CLOSE` — price summaries from `data_feed.add_source_columns`
- `h_set`, `l_set` — selected source based on `config.SOURCE_MODE`

Any additional columns (ATR bands, Supertrend, TCI, ADX, etc.) are the **exclusive responsibility** of the strategy's `prepare_dataframe(df)` method, called by `apply_strategy_processing`.

---

## Part D — Parametrize `_open_advanced_buy` execution rules

### D1. New payload fields

Three new float fields in the signal payload:

| Field | Default | Meaning |
|-------|---------|---------|
| `sl_atr_mult` | 1.0 | SL distance = `sl_atr_mult * atr_value` below entry |
| `tp_atr_mult` | 2.0 | TP distance = `tp_atr_mult * atr_value` above entry |
| `pyramid_atr_mult` | 0.5 | Pyramid threshold = `last_entry + pyramid_atr_mult * atr_value` |

Defaults preserve existing behavior (first strategy uses 1.0/2.0/0.5).

### D2. Extension to `normalize_signal_payload` in `strategy_runtime.py`

Add after the existing `volume_ratio` block (currently ending at line ~127):

```
sl_atr_mult_raw = payload.get("sl_atr_mult", 1.0) if isinstance(payload, dict) else 1.0
try:
    sl_atr_mult = float(sl_atr_mult_raw) if sl_atr_mult_raw is not None else 1.0
except (TypeError, ValueError):
    sl_atr_mult = 1.0

tp_atr_mult_raw = payload.get("tp_atr_mult", 2.0) if isinstance(payload, dict) else 2.0
try:
    tp_atr_mult = float(tp_atr_mult_raw) if tp_atr_mult_raw is not None else 2.0
except (TypeError, ValueError):
    tp_atr_mult = 2.0

pyramid_atr_mult_raw = payload.get("pyramid_atr_mult", 0.5) if isinstance(payload, dict) else 0.5
try:
    pyramid_atr_mult = float(pyramid_atr_mult_raw) if pyramid_atr_mult_raw is not None else 0.5
except (TypeError, ValueError):
    pyramid_atr_mult = 0.5
```

Add to the returned dict:
```
"sl_atr_mult": sl_atr_mult,
"tp_atr_mult": tp_atr_mult,
"pyramid_atr_mult": pyramid_atr_mult,
```

### D3. Changes to `_open_advanced_buy` in `backtesting/runtime.py`

Read multipliers from `signal_payload` (with safe fallbacks):

```
sl_atr_mult     = float(signal_payload.get("sl_atr_mult") or 1.0)
tp_atr_mult     = float(signal_payload.get("tp_atr_mult") or 2.0)
pyramid_atr_mult = float(signal_payload.get("pyramid_atr_mult") or 0.5)
```

Replace hardcoded literal `0.5` in pyramid threshold check (currently line ~480):
```
# BEFORE:
pyramid_threshold = float(most_recent["entry_price"]) + (0.5 * atr_value)
# AFTER:
pyramid_threshold = float(most_recent["entry_price"]) + (pyramid_atr_mult * atr_value)
```

Replace hardcoded SL/TP literals in `_new_position` call (currently lines ~499-500):
```
# BEFORE:
sl=entry_price - atr_value,
tp=entry_price + (2.0 * atr_value),
# AFTER:
sl=entry_price - (sl_atr_mult * atr_value),
tp=entry_price + (tp_atr_mult * atr_value),
```

---

## Part E — DataProvider Protocol and canonical symbol registry

### E1. `DataProvider` Protocol

New file: `backtesting/providers.py` (or `src/data/interface.py` per broker abstraction sprint — Felix must use whichever location is consistent with TASK-034 spec when it exists).

For TASK-027 scope, the Protocol is defined **conceptually** here; the actual file location and import path are decided in TASK-034. Felix implements the existing engine changes assuming the Protocol will be injected later.

```
Protocol DataProvider:
    method get_rates_df(
        symbol: str,          # canonical symbol name (e.g. "GER40")
        timeframe: str,       # timeframe label (e.g. "M1", "H1")
        start: datetime,      # UTC-aware
        end: datetime         # UTC-aware
    ) -> pd.DataFrame:
        # Returns OHLCV DataFrame with columns: time (UTC datetime), open, high, low, close, volume
        # Raises RuntimeError if no data available

    method get_instrument_info(
        symbol: str           # canonical symbol name
    ) -> dict:
        # Returns: {"point": float, "tick_size": float, "tick_value": float}
        # Raises RuntimeError if symbol unknown
```

### E2. Canonical symbol registry

File: `backtesting/symbols.py` (new file, created by Felix in this task).

Structure:

```python
SYMBOL_REGISTRY = {
    "GER40": {
        "point": 1.0,
        "tick_size": 1.0,
        "tick_value": 1.0,
        "providers": {
            "mt5": "#Germany40",
            "dukascopy": "DEU.IDX/EUR",
        }
    },
    # future: "EURUSD": {...}, etc.
}
```

### E3. Instrument metadata resolution logic

```
function resolve_instrument_info(symbol_canonical, provider=None):
    entry = SYMBOL_REGISTRY.get(symbol_canonical)
    if entry is None:
        raise RuntimeError(f"Unknown canonical symbol: {symbol_canonical}")

    # Start with registry defaults
    point      = entry["point"]
    tick_size  = entry["tick_size"]
    tick_value = entry["tick_value"]

    # If provider supplies overrides, use them
    if provider is not None and hasattr(provider, "get_instrument_info"):
        try:
            override = provider.get_instrument_info(symbol_canonical)
            point      = override.get("point", point)
            tick_size  = override.get("tick_size", tick_size)
            tick_value = override.get("tick_value", tick_value)
        except Exception:
            pass  # fall back to registry defaults silently

    return {"point": point, "tick_size": tick_size, "tick_value": tick_value}
```

### E4. MT5 metadata call sites to replace in `backtesting/runtime.py`

Current MT5-coupled call sites (all in `BacktestEngine.__init__`, lines 181–194):

```python
# BEFORE (lines 181-194) — DELETE all of this:
self.symbol_info = mt5.symbol_info(self.symbol)
if self.symbol_info is None:
    raise RuntimeError(...)
self.point = float(getattr(self.symbol_info, "point", 0.0) or 0.0)
self.tick_size = float(getattr(self.symbol_info, "trade_tick_size", 0.0) or 0.0)
self.tick_value = float(getattr(self.symbol_info, "trade_tick_value", 0.0) or 0.0)
if self.point <= 0:
    self.point = self.tick_size
if self.tick_size <= 0 or self.tick_value <= 0:
    raise RuntimeError(...)
self.value_per_price_unit_per_lot = self.tick_value / self.tick_size

# AFTER — replace with registry resolution:
info = resolve_instrument_info(self.symbol)
self.point      = info["point"]
self.tick_size  = info["tick_size"]
self.tick_value = info["tick_value"]
if self.tick_size <= 0 or self.tick_value <= 0:
    raise RuntimeError(f"Symbol {self.symbol} has invalid tick metadata in registry")
self.value_per_price_unit_per_lot = self.tick_value / self.tick_size
```

Note: `_normalize_volume` currently calls `trading.normalize_volume(lot, self.symbol_info)`. With MT5 decoupled, `self.symbol_info` is no longer available. For this task, `_normalize_volume` should return the requested lot unchanged (identity) when not in MT5 context. The full volume normalization refactor is part of TASK-037 (broker abstraction). **Felix must change `_normalize_volume` to return `(float(requested_lot), None)` unconditionally for now**, removing the call to `trading.normalize_volume`.

Similarly, `_open_advanced_buy` calls `trading.calculate_dynamic_lot` and `trading.check_aggregate_risk` which internally call `mt5.symbol_info`. These calls must be guarded or simplified for the non-MT5 path. For this task, if `self.symbol_info` is None (no MT5), `_open_advanced_buy` should skip dynamic sizing and aggregate risk checks and proceed with `self.request.lot` directly.

### E5. Cache structure for data providers

**Directory**: `backtesting/cache/<provider>/<symbol_canonical>/`

**File naming**: `<symbol_canonical>_<timeframe>_<YYYY-MM-DD>_<YYYY-MM-DD>.parquet`

Example:
```
backtesting/cache/dukascopy/GER40/GER40_M1_2023-01-01_2024-01-01.parquet
backtesting/cache/mt5/GER40/GER40_H1_2024-01-01_2025-01-01.parquet
```

The cache is not implemented in this task (TASK-027). This structure is documented here so TASK-040 (Dukascopy spike) uses a consistent naming convention.

### E6. Provider field in result

Add to `_build_success_result`:

```python
"data_provider": str(self.request.data_provider) if hasattr(self.request, "data_provider") else "mt5"
```

`BacktestRequest` gains an optional field:
```python
data_provider: str = "mt5"   # canonical provider name shown in GUI
```

---

## Pseudocode Spec

### Change 1: `BacktestRequest` dataclass additions

```
@dataclass BacktestRequest:
    # ... existing fields unchanged ...
    spread_points: float = 0.0
    slippage_points: float = 0.0
    commission_per_lot: float = 0.0
    data_provider: str = "mt5"
```

In `from_dict`, after existing field parsing:
```
spread_points       = float(raw.get("spread_points") or 0.0)
slippage_points     = float(raw.get("slippage_points") or 0.0)
commission_per_lot  = float(raw.get("commission_per_lot") or 0.0)
data_provider       = str(raw.get("data_provider") or "mt5")
```

---

### Change 2: `BacktestEngine.__init__` — decouple from MT5 metadata

```
# Replace mt5.symbol_info block with:
info = resolve_instrument_info(self.symbol)
self.point      = info["point"]
self.tick_size  = info["tick_size"]
self.tick_value = info["tick_value"]
if self.tick_size <= 0 or self.tick_value <= 0:
    raise RuntimeError(f"Symbol {self.symbol} has invalid tick metadata in registry")
self.value_per_price_unit_per_lot = self.tick_value / self.tick_size
self.symbol_info = None  # no longer used
```

---

### Change 3: `_normalize_volume` — identity for non-MT5 path

```
def _normalize_volume(self, requested_lot: float) -> tuple[float, str | None]:
    return (max(0.0, float(requested_lot or 0.0)), None)
```

(Full volume normalization deferred to TASK-037.)

---

### Change 4: Remove hardcoded indicators from `_build_market_dataframe`

Delete lines 88–102 (the three `data_feed.add_*` calls). Function returns after `df = data_feed.add_source_columns(df, config.SOURCE_MODE)`.

---

### Change 5: `_apply_standard_signal` — apply spread/slippage/commission

```
def _apply_standard_signal(self, candle, signal_payload):
    signal = signal_payload.get("signal", "none")
    if signal not in {"buy", "sell"}:
        return

    direction = 1 if signal == "buy" else -1
    current_direction = self._current_direction()
    raw_fill = float(candle["open"])

    if current_direction == direction:
        return

    if current_direction != 0:
        self._close_all_positions(candle=candle, exit_price=raw_fill, reason="REVERSAL")

    lot, volume_note = self._normalize_volume(self.request.lot)
    if lot <= 0:
        return

    # Apply transaction costs to fill price
    cost_points = (self.request.spread_points + self.request.slippage_points) * self.point
    if direction == 1:
        entry_price = raw_fill + cost_points
        sl = entry_price - (self.request.sl_points * self.point) if self.request.sl_points > 0 else 0.0
        tp = entry_price + (self.request.tp_points * self.point) if self.request.tp_points > 0 else 0.0
    else:
        entry_price = raw_fill - cost_points
        sl = entry_price + (self.request.sl_points * self.point) if self.request.sl_points > 0 else 0.0
        tp = entry_price - (self.request.tp_points * self.point) if self.request.tp_points > 0 else 0.0

    # Commission at open
    self.balance -= self.request.commission_per_lot * lot

    self._new_position(
        candle=candle, direction=direction, volume=lot,
        entry_price=entry_price, sl=sl, tp=tp,
        signal=signal, signal_reason=str(signal_payload.get("reason") or ""),
        mode="standard", volume_note=volume_note,
    )
```

---

### Change 6: `_open_advanced_buy` — apply costs + read payload multipliers

```
def _open_advanced_buy(self, candle, signal_payload):
    atr_value = float(signal_payload.get("atr_value") or 0.0)
    if atr_value <= 0:
        return

    sl_atr_mult      = float(signal_payload.get("sl_atr_mult") or 1.0)
    tp_atr_mult      = float(signal_payload.get("tp_atr_mult") or 2.0)
    pyramid_atr_mult = float(signal_payload.get("pyramid_atr_mult") or 0.5)

    # Volume selection (dynamic sizing skipped if not in MT5 context)
    dynamic_sizing = bool(signal_payload.get("dynamic_sizing"))
    volume_ratio   = float(signal_payload.get("volume_ratio") or 0.0)
    requested_lot  = self.request.lot  # dynamic sizing deferred (no MT5 for symbol_info)

    lot, volume_note = self._normalize_volume(requested_lot)
    if lot <= 0:
        return

    raw_fill = float(candle["open"])
    cost_points = (self.request.spread_points + self.request.slippage_points) * self.point
    entry_price = raw_fill + cost_points  # BUY direction only

    # Pyramiding threshold check
    if self.open_positions:
        most_recent = max(self.open_positions,
                          key=lambda p: (_time_to_epoch(p["entry_time"]) or 0, p["id"]))
        if most_recent["direction"] != 1:
            return
        pyramid_threshold = float(most_recent["entry_price"]) + (pyramid_atr_mult * atr_value)
        if entry_price < pyramid_threshold:
            return

    # Commission at open
    self.balance -= self.request.commission_per_lot * lot

    self._new_position(
        candle=candle, direction=1, volume=lot,
        entry_price=entry_price,
        sl=entry_price - (sl_atr_mult * atr_value),
        tp=entry_price + (tp_atr_mult * atr_value),
        signal="buy",
        signal_reason=str(signal_payload.get("reason") or ""),
        mode="advanced",
        atr_value=atr_value,
        volume_ratio=volume_ratio,
        dynamic_sizing=dynamic_sizing,
        volume_note=volume_note,
    )
```

Note: `trading.calculate_dynamic_lot` and `trading.check_aggregate_risk` are removed from `_open_advanced_buy` for this task. They require `mt5.symbol_info` internally. Full reinstatement via the `IBrokerAdapter` interface is deferred to TASK-035/TASK-037.

---

### Change 7: `_close_position` — apply commission at close

```
def _close_position(self, position, *, candle_time, exit_price, reason, forced=False):
    profit = self._calculate_profit(
        position["entry_price"], exit_price,
        position["direction"], position["volume"],
    )
    self.balance += profit
    # Commission at close
    self.balance -= self.request.commission_per_lot * position["volume"]

    self.closed_trades.append({
        # ... existing fields unchanged ...
    })
    self.open_positions = [p for p in self.open_positions if p["id"] != position["id"]]
```

---

### Change 8: `_build_success_result` — full replacement

```
def _build_success_result(self) -> dict:
    total_profit    = self.balance - self.initial_balance
    closed_count    = len(self.closed_trades)
    winning_trades  = sum(1 for t in self.closed_trades if t["profit"] > 0)
    losing_trades   = sum(1 for t in self.closed_trades if t["profit"] < 0)
    win_rate        = (winning_trades / closed_count * 100.0) if closed_count else 0.0

    # Gross aggregates — single O(n) pass
    gross_wins   = sum(t["profit"] for t in self.closed_trades if t["profit"] > 0)
    gross_losses = sum(-t["profit"] for t in self.closed_trades if t["profit"] < 0)  # positive

    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0.0
    avg_win       = gross_wins / winning_trades if winning_trades > 0 else 0.0
    avg_loss      = gross_losses / losing_trades if losing_trades > 0 else 0.0
    loss_rate     = losing_trades / closed_count if closed_count > 0 else 0.0
    expectancy    = (win_rate / 100.0) * avg_win - loss_rate * avg_loss

    # Drawdown curve — single O(n) pass
    drawdown_curve = []
    running_peak   = self.initial_balance
    for point in self.equity_curve:
        eq = point["equity"]
        if eq > running_peak:
            running_peak = eq
        dd_pct = ((running_peak - eq) / running_peak * 100.0) if running_peak > 0 else 0.0
        drawdown_curve.append({"time": point["time"], "drawdown_pct": round(dd_pct, 4)})

    return {
        "status": "success",
        "error": "",
        "strategy_key":    self.request.strategy_key,
        "strategy_label":  self.request.strategy_label,
        "symbol":          self.symbol,
        "timeframe":       self.timeframe_label,
        "data_provider":   self.request.data_provider,
        "start_date":      _time_to_epoch(self.request.start_date),
        "end_date":        _time_to_epoch(self.request.end_date),
        "initial_balance": self.initial_balance,
        "final_balance":   self.balance,
        "total_profit":    total_profit,
        "total_return_pct": (total_profit / self.initial_balance * 100.0),
        "closed_trades":   closed_count,
        "winning_trades":  winning_trades,
        "losing_trades":   losing_trades,
        "win_rate":        win_rate,
        "max_drawdown":    self.max_drawdown,
        "profit_factor":   round(profit_factor, 4),
        "avg_win":         round(avg_win, 4),
        "avg_loss":        round(avg_loss, 4),
        "expectancy":      round(expectancy, 4),
        "cost_params": {
            "spread_points":      self.request.spread_points,
            "slippage_points":    self.request.slippage_points,
            "commission_per_lot": self.request.commission_per_lot,
        },
        "trades":          self.closed_trades,
        "equity_curve":    self.equity_curve,
        "drawdown_curve":  drawdown_curve,
    }
```

---

### Change 9: `normalize_signal_payload` extension in `strategy_runtime.py`

After the existing `volume_ratio` block (currently ends ~line 127), add inside the `if isinstance(payload, dict):` block:

```
sl_atr_mult_raw = payload.get("sl_atr_mult", 1.0)
try:
    sl_atr_mult = float(sl_atr_mult_raw) if sl_atr_mult_raw is not None else 1.0
except (TypeError, ValueError):
    sl_atr_mult = 1.0

tp_atr_mult_raw = payload.get("tp_atr_mult", 2.0)
try:
    tp_atr_mult = float(tp_atr_mult_raw) if tp_atr_mult_raw is not None else 2.0
except (TypeError, ValueError):
    tp_atr_mult = 2.0

pyramid_atr_mult_raw = payload.get("pyramid_atr_mult", 0.5)
try:
    pyramid_atr_mult = float(pyramid_atr_mult_raw) if pyramid_atr_mult_raw is not None else 0.5
except (TypeError, ValueError):
    pyramid_atr_mult = 0.5
```

For the `elif isinstance(payload, (tuple, list)):` branch, all three default to their numeric defaults (1.0, 2.0, 0.5) since the tuple format carries no extra fields.

Add to the returned dict:
```
"sl_atr_mult":      sl_atr_mult,
"tp_atr_mult":      tp_atr_mult,
"pyramid_atr_mult": pyramid_atr_mult,
```

---

### New file: `backtesting/symbols.py`

```python
SYMBOL_REGISTRY = {
    "GER40": {
        "point": 1.0,
        "tick_size": 1.0,
        "tick_value": 1.0,
        "providers": {
            "mt5": "#Germany40",
            "dukascopy": "DEU.IDX/EUR",
        },
    },
}


def resolve_instrument_info(symbol_canonical: str) -> dict:
    entry = SYMBOL_REGISTRY.get(symbol_canonical)
    if entry is None:
        raise RuntimeError(f"Unknown canonical symbol: {symbol_canonical!r}. "
                           f"Add it to backtesting/symbols.py.")
    return {
        "point":      float(entry["point"]),
        "tick_size":  float(entry["tick_size"]),
        "tick_value": float(entry["tick_value"]),
    }
```

---

## Files Changed

| File | Change |
|------|--------|
| `backtesting/runtime.py` | `BacktestRequest`: add `spread_points`, `slippage_points`, `commission_per_lot`, `data_provider`; `BacktestEngine.__init__`: replace MT5 metadata block with `resolve_instrument_info`; `_normalize_volume`: identity passthrough; `_build_market_dataframe`: remove 3 hardcoded indicator calls; `_apply_standard_signal`: apply cost to fill price + commission deduction; `_open_advanced_buy`: read `sl/tp/pyramid_atr_mult`, apply cost, remove MT5-coupled dynamic sizing/risk calls, commission deduction; `_close_position`: commission deduction at close; `_build_success_result`: add equity_curve, drawdown_curve, profit_factor, avg_win, avg_loss, expectancy, cost_params, data_provider |
| `strategy_runtime.py` | `normalize_signal_payload`: add `sl_atr_mult`, `tp_atr_mult`, `pyramid_atr_mult` extraction and passthrough |
| `backtesting/symbols.py` | New file: `SYMBOL_REGISTRY` + `resolve_instrument_info()` |

**Do not modify**: `gui_charts.py`, `trading.py`, `data_feed.py`, `main.py`, `config.py`

---

## JSON-serializability check

All new fields in `_build_success_result`:
- `equity_curve`: `list[{"time": int, "equity": float, "balance": float}]` — ✅ native JSON
- `drawdown_curve`: `list[{"time": int, "drawdown_pct": float}]` — ✅ native JSON
- `profit_factor`, `avg_win`, `avg_loss`, `expectancy`: `float` — ✅ native JSON
- `cost_params`: `dict[str, float]` — ✅ native JSON
- `data_provider`: `str` — ✅ native JSON

All float values produced by Python arithmetic on Python `float` operands — no `np.float64` introduced.
