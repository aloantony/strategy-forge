# Pre-Implementation: run_backtest_comparison

**By**: Daniel
**Date**: 2026-04-11
**Task**: TASK-029
**Status**: ready

---

## Formal Problem Statement

**Input**: `request: dict` — comparison request containing a symbol, date range, shared trading params, and a list of N strategy descriptors (N ≥ 1; GUI will enforce N ≥ 2). Each strategy descriptor carries its module object, strategy keys/labels, and an optional timeframe override.

**Output**: `dict` — JSON-serializable comparison result with top-level status, shared context fields (symbol, dates, initial_balance), and a `strategies` array with one summary-metrics entry per strategy. No `trades` or `equity_curve` arrays — comparison output is summary-only.

**Constraints**:
- JSON-serializable (no datetime objects, no MT5 objects in output)
- Must run in a background thread (same daemon-thread pattern as `run_backtest`)
- MT5 data download is the dominant latency cost; must be amortized across strategies sharing the same timeframe
- N typically 2–5; sequential per-strategy execution is acceptable (total budget: N × single-backtest time)
- Partial failure must not abort the comparison — if one strategy errors, remaining strategies continue

**Invariants**:
- All strategies share the same `symbol`, `start_date`, `end_date`, `initial_balance`, and trading params (`lot`, `sl_points`, `tp_points`, and cost params once TASK-027 lands)
- Each strategy may declare its own `timeframe_value`; strategies that omit it inherit the top-level default
- `module` objects inside `strategies[]` are resolved by the GUI before the request is built (same pattern as today's `_on_backtest_run`)

**Clarity**: ✅ clear

---

## Candidate Algorithms

### 1. Independent download per strategy
- **Description**: Each `BacktestEngine` calls `_build_market_dataframe` for its own data. Identical to calling `run_backtest` N times sequentially.
- **Time**: O(D × N + C × N) where D = MT5 download cost (~100–500 ms), C = candle iteration cost per strategy
- **Space**: O(C) peak (one df at a time)
- **Verdict**: eliminated
- **Reason**: D is the bottleneck. With N=5, independent downloads waste 400–2000 ms of avoidable MT5 round-trips. Shares nothing.

### 2. Shared DataFrame per timeframe group, sequential execution
- **Description**: Group strategies by (symbol, timeframe_value). Download base df once per group. Each engine receives the base df directly instead of re-downloading. Strategies iterate sequentially within each group.
- **Time**: O(D × G + C × N) where G = number of distinct timeframes (typically 1–2), C = candle iteration per strategy
- **Space**: O(C × N) worst-case (one base df per group, one copy per strategy during processing)
- **Verdict**: selected
- **Reason**: Eliminates O(D × (N − G)) redundant downloads. With N=5 all on M1, cost drops from 5D to 1D. Sequential execution avoids MT5 thread-safety concerns entirely and is simpler to test. For N=2–5 the parallelism gain of Candidate 3 does not justify the added complexity.

### 3. Shared DataFrame, parallel execution (ThreadPoolExecutor)
- **Description**: Same shared df as Candidate 2, but each strategy engine runs in a worker thread concurrently.
- **Time**: O(D × G + C) wall-clock (strategies overlap)
- **Space**: O(C × N) (all copies live concurrently)
- **Verdict**: viable but not selected
- **Reason**: `BacktestEngine.__init__` calls `mt5.symbol_info()` which is safe, but strategy signal functions (`get_last_signal_payload`) are user-supplied and their thread-safety is not guaranteed. For N=2–5 the wall-clock saving is 15–60 s — meaningful but not required. Adopt if N grows beyond 5 in a future task.

---

## Selected Algorithm

**Winner**: Shared DataFrame per timeframe group, sequential execution

**Justification**:
- G=1 (most comparisons use one timeframe), so download cost D occurs once regardless of N
- C × N with N=5 on 500-candle backtest is ~10–30 s total — acceptable for a user-initiated comparison
- MT5 is already being used by the bot-loop thread concurrently; adding parallel backtest threads introduces coordination risk with no runtime contract. Sequential avoids this entirely.
- Trade-off accepted: wall-clock time scales linearly with N. Mitigated by DataFrame sharing, which removes the dominant D term.

---

## Function Signature and Request/Result Shapes

### New public function

```
run_backtest_comparison(request: dict) -> dict
```

Called from a new GUI worker method (`_run_backtest_comparison_worker`) in the same daemon-thread pattern as `_run_backtest_worker`.

### Comparison request shape (input dict)

Required fields:
```
symbol:          str                 — trading symbol (e.g. "#Germany40")
start_date:      datetime|Timestamp  — range start (UTC)
end_date:        datetime|Timestamp  — range end (UTC)
initial_balance: float               — must be > 0
strategies:      list[dict]          — min 1 item (GUI enforces ≥ 2)
```

Each item in `strategies[]`:
```
strategy_key:    str    — required; unique identifier
strategy_label:  str    — optional; display name (defaults to strategy_key)
module:          Any    — required; loaded Python module object
timeframe_value: int    — optional; MT5 TIMEFRAME_* constant; defaults to top-level timeframe
```

Optional top-level fields (all default to config values):
```
timeframe:           str    — e.g. "M1"; default timeframe if strategy omits timeframe_value
warmup_bars:         int    — default: max(config.BARS_HISTORY, 500)
lot:                 float  — default: config.LOT
sl_points:           float  — default: config.SL_POINTS
tp_points:           float  — default: config.TP_POINTS
spread_points:       float  — default: 0.0  (TASK-027 cost param, pass-through)
slippage_points:     float  — default: 0.0  (TASK-027 cost param, pass-through)
commission_per_lot:  float  — default: 0.0  (TASK-027 cost param, pass-through)
```

### Comparison result shape (output dict)

Top-level:
```json
{
  "status":          "success" | "partial" | "error",
  "error":           "string",
  "symbol":          "string",
  "start_date":      int,
  "end_date":        int,
  "initial_balance": float,
  "strategies":      [ <StrategyComparisonEntry>, ... ]
}
```

`status` rules:
- `"success"` — all strategies ran without error
- `"partial"` — at least one succeeded and at least one failed
- `"error"` — all strategies failed, or the request itself was invalid (no `strategies` array run at all)

Each `StrategyComparisonEntry`:
```json
{
  "status":           "success" | "error",
  "error":            "string",
  "strategy_key":     "string",
  "strategy_label":   "string",
  "timeframe":        "string",
  "initial_balance":  float,
  "final_balance":    float,
  "total_profit":     float,
  "total_return_pct": float,
  "closed_trades":    int,
  "winning_trades":   int,
  "losing_trades":    int,
  "win_rate":         float,
  "max_drawdown":     float
}
```

Note: `trades` (individual trade list) and `equity_curve` are intentionally excluded from comparison entries. They are large arrays (500+ items) unnecessary for the summary table the GUI renders. If a user wants per-trade detail, they run a single backtest.

On error entries, numeric metric fields are set to their zero/identity defaults (see `_empty_metrics` in pseudocode).

The `strategies` array preserves the order of the input `strategies[]` list, regardless of the internal grouping by timeframe.

---

## Error Handling

| Failure point | Behaviour |
|---|---|
| Invalid top-level request (bad symbol, missing `strategies`, bad dates, initial_balance ≤ 0) | Return `{"status": "error", "error": "..."}` immediately; no engines run |
| `_build_market_dataframe` raises for a timeframe group | All strategies in that group get `status: "error"` with the download error message; other groups continue |
| `BacktestEngine.__init__` raises (bad symbol_info) | That strategy entry gets `status: "error"`; remaining strategies continue |
| `engine.run_with_df` raises or returns `status: "error"` | That strategy entry gets `status: "error"`; remaining strategies continue |
| All strategies fail | Top-level `status: "error"`, `error` field concatenates all per-strategy error messages |
| Some strategies fail | Top-level `status: "partial"`, `error` = "N de M estrategias fallaron" |

---

## Pseudocode Spec

```
function run_backtest_comparison(request: dict) -> dict:
    # --- Validate top-level fields ---
    if not isinstance(request, dict):
        return {"status": "error", "error": "El request debe ser un dict"}

    symbol = str(request.get("symbol") or "").strip()
    if not symbol:
        return {"status": "error", "error": "Se requiere símbolo"}

    try:
        start_date = _as_utc_datetime(request["start_date"])
        end_date   = _as_utc_datetime(request["end_date"])
    except Exception as e:
        return {"status": "error", "error": f"Fechas inválidas: {e}"}

    if end_date < start_date:
        return {"status": "error", "error": "La fecha fin no puede ser anterior a la fecha inicio"}

    initial_balance = float(request.get("initial_balance") or 0.0)
    if initial_balance <= 0:
        return {"status": "error", "error": "El balance inicial debe ser mayor que cero"}

    strategies_raw = list(request.get("strategies") or [])
    if not strategies_raw:
        return {"status": "error", "error": "Se requiere al menos una estrategia"}

    # Shared trading params
    warmup_bars        = max(1, int(request.get("warmup_bars") or _default_warmup_bars()))
    lot                = float(request.get("lot") or config.LOT or 0.01)
    sl_points          = float(request.get("sl_points") or config.SL_POINTS or 0.0)
    tp_points          = float(request.get("tp_points") or config.TP_POINTS or 0.0)
    spread_points      = float(request.get("spread_points") or 0.0)
    slippage_points    = float(request.get("slippage_points") or 0.0)
    commission_per_lot = float(request.get("commission_per_lot") or 0.0)

    default_tv = resolve_timeframe_value(request.get("timeframe")) or TIMEFRAME_MAP["M1"]

    # --- Group strategies by timeframe_value ---
    # groups: dict[timeframe_value -> list of (original_index, strat_dict)]
    groups = {}
    for i, strat in enumerate(strategies_raw):
        tv = int(strat.get("timeframe_value") or default_tv)
        if tv not in groups:
            groups[tv] = []
        groups[tv].append((i, strat))

    # results_by_index: dict[original_index -> result_entry]
    results_by_index = {}

    # --- Process each timeframe group ---
    for tv, indexed_strats in groups.items():
        # Download base df once for this timeframe group
        try:
            base_df = _build_market_dataframe(symbol, tv, start_date, end_date, warmup_bars)
        except Exception as e:
            for idx, strat in indexed_strats:
                results_by_index[idx] = _make_error_entry(
                    strat,
                    timeframe_label(tv),
                    initial_balance,
                    f"Error descargando datos ({timeframe_label(tv)}): {e}",
                )
            continue

        # Run each strategy sequentially against a copy of the base df
        for idx, strat in indexed_strats:
            module = strat.get("module")
            if module is None:
                results_by_index[idx] = _make_error_entry(
                    strat, timeframe_label(tv), initial_balance,
                    "La estrategia no tiene módulo cargado"
                )
                continue

            strat_request = BacktestRequest(
                strategy_key   = str(strat.get("strategy_key") or "strategy"),
                strategy_label = str(strat.get("strategy_label") or strat.get("strategy_key") or "Strategy"),
                module         = module,
                symbol         = symbol,
                timeframe_value= tv,
                start_date     = start_date,
                end_date       = end_date,
                initial_balance= initial_balance,
                warmup_bars    = warmup_bars,
                lot            = lot,
                sl_points      = sl_points,
                tp_points      = tp_points,
                # TASK-027 cost params (pass through; BacktestRequest will carry them once TASK-027 lands)
                # spread_points=spread_points, slippage_points=slippage_points,
                # commission_per_lot=commission_per_lot
            )

            try:
                engine = BacktestEngine(strat_request)
                individual = engine.run_with_df(base_df.copy())
            except Exception as e:
                results_by_index[idx] = _make_error_entry(
                    strat, timeframe_label(tv), initial_balance, str(e)
                )
                continue

            results_by_index[idx] = _extract_comparison_summary(individual, initial_balance)

    # --- Re-assemble in original input order ---
    results = [results_by_index[i] for i in range(len(strategies_raw))]

    # --- Determine top-level status ---
    success_count = sum(1 for r in results if r["status"] == "success")
    error_count   = sum(1 for r in results if r["status"] == "error")

    if success_count == 0:
        top_status = "error"
        top_error  = "; ".join(r["error"] for r in results if r["error"])
    elif error_count > 0:
        top_status = "partial"
        top_error  = f"{error_count} de {len(results)} estrategias fallaron"
    else:
        top_status = "success"
        top_error  = ""

    return {
        "status":          top_status,
        "error":           top_error,
        "symbol":          symbol,
        "start_date":      _time_to_epoch(start_date),
        "end_date":        _time_to_epoch(end_date),
        "initial_balance": initial_balance,
        "strategies":      results,
    }


function _extract_comparison_summary(result: dict, fallback_balance: float) -> dict:
    # Converts a full individual backtest result dict into a comparison summary entry.
    # Strips trades[] and equity_curve[] (not needed for comparison table).
    if result.get("status") != "success":
        return {
            "status":           "error",
            "error":            str(result.get("error") or ""),
            "strategy_key":     str(result.get("strategy_key") or ""),
            "strategy_label":   str(result.get("strategy_label") or ""),
            "timeframe":        str(result.get("timeframe") or ""),
            **_empty_metrics(fallback_balance),
        }
    return {
        "status":           "success",
        "error":            "",
        "strategy_key":     result["strategy_key"],
        "strategy_label":   result["strategy_label"],
        "timeframe":        result["timeframe"],
        "initial_balance":  result["initial_balance"],
        "final_balance":    result["final_balance"],
        "total_profit":     result["total_profit"],
        "total_return_pct": result["total_return_pct"],
        "closed_trades":    result["closed_trades"],
        "winning_trades":   result["winning_trades"],
        "losing_trades":    result["losing_trades"],
        "win_rate":         result["win_rate"],
        "max_drawdown":     result["max_drawdown"],
    }


function _make_error_entry(strat: dict, tf_label: str, initial_balance: float, error: str) -> dict:
    return {
        "status":         "error",
        "error":          error,
        "strategy_key":   str(strat.get("strategy_key") or ""),
        "strategy_label": str(strat.get("strategy_label") or strat.get("strategy_key") or ""),
        "timeframe":      tf_label,
        **_empty_metrics(initial_balance),
    }


function _empty_metrics(initial_balance: float) -> dict:
    # Zero/identity values for all numeric summary fields when a strategy errors.
    return {
        "initial_balance":  initial_balance,
        "final_balance":    initial_balance,
        "total_profit":     0.0,
        "total_return_pct": 0.0,
        "closed_trades":    0,
        "winning_trades":   0,
        "losing_trades":    0,
        "win_rate":         0.0,
        "max_drawdown":     0.0,
    }
```

### New method on BacktestEngine

```
method BacktestEngine.run_with_df(base_df: pd.DataFrame) -> dict:
    # Identical to run() but receives a pre-built market DataFrame.
    # Skips the _build_market_dataframe call (no MT5 download).
    # base_df: raw market DataFrame (OHLCV + source columns); already a copy — safe to mutate.

    try:
        strategy_df = apply_strategy_processing(
            base_df,
            self.module,
            enable_signals=bool(getattr(config, "ENABLE_SIGNALS", True)),
        )
    except Exception as error:
        return {"status": "error", "error": str(error)}

    # ---- everything below is identical to the body of run() after the df acquisition ----

    if strategy_df is None or strategy_df.empty or "time" not in strategy_df.columns:
        return {"status": "error", "error": "La estrategia no devolvió datos válidos para backtest"}

    strategy_df = strategy_df.sort_values("time").reset_index(drop=True)
    time_series  = pd.to_datetime(strategy_df["time"], utc=True)
    visible_mask = (
        (time_series >= pd.Timestamp(self.request.start_date))
        & (time_series <= pd.Timestamp(self.request.end_date))
    )
    visible_indices = strategy_df.index[visible_mask].tolist()
    if not visible_indices:
        return {"status": "error", "error": "No hay velas dentro del rango solicitado"}

    last_visible_index  = int(visible_indices[-1])
    first_visible_index = int(visible_indices[0])
    pending_signal = None

    if first_visible_index > 0:
        prefix_df = strategy_df.iloc[: first_visible_index + 1]
        try:
            pending_signal = get_strategy_signal_payload(prefix_df, self.module, verbose=False)
        except Exception as error:
            return {"status": "error", "error": str(error)}

    for idx in visible_indices:
        candle = strategy_df.iloc[int(idx)]
        if pending_signal is not None:
            self._apply_pending_signal(candle, pending_signal)
            pending_signal = None

        self._process_candle_exits(candle)
        self._mark_equity(candle)

        next_index = int(idx) + 1
        if next_index > last_visible_index:
            continue

        prefix_df = strategy_df.iloc[: next_index + 1]
        try:
            pending_signal = get_strategy_signal_payload(prefix_df, self.module, verbose=False)
        except Exception as error:
            return {"status": "error", "error": str(error)}

    last_candle = strategy_df.iloc[last_visible_index]
    if self.open_positions:
        self._close_all_positions(
            candle=last_candle,
            exit_price=float(last_candle["close"]),
            reason="END_OF_RANGE",
            forced=True,
        )
        self._mark_equity(last_candle)

    return self._build_success_result()
```

**Implementation note**: The coding agent should implement `run_with_df` as a new method on `BacktestEngine` and refactor `run()` to call `run_with_df(df)` after building the market dataframe — eliminating code duplication entirely.

---

## Notes for Downstream Agents

- **TASK-027 cost params**: Once `BacktestRequest` gains `spread_points`, `slippage_points`, `commission_per_lot` (TASK-027), the comparison function must pass these through to each `BacktestRequest`. The pseudocode already extracts them from the request dict with default 0.0.
- **Grace (TASK-030)**: The GUI comparison handler follows the same pattern as `_on_backtest_run` / `_run_backtest_worker`. The new handler (`_on_backtest_compare` / `_run_backtest_comparison_worker`) resolves modules for each strategy key, builds the comparison request dict, and calls `run_backtest_comparison(request)` in a daemon thread. The result lands in `backtest_state["comparison_result"]` (or equivalent state key). Grace defines the exact threading and state slot.
- **`_build_market_dataframe` indicators**: The function currently adds `baseline_bands`, `supertrend`, `TCI` columns. These are shared across all strategies in a group — benign, since `apply_strategy_processing` → `prepare_dataframe` adds columns but does not remove or overwrite existing ones. When those indicator additions are removed from the engine (future cleanup), the base df will be OHLCV + source columns only; the spec remains valid.
