# Review: add_supertrend() (data_feed.py:134)

**Reviewed by**: Daniel
**Date**: 2026-03-30
**Status**: complete

---

## Problem Statement

`add_supertrend()` computes the Supertrend indicator and appends four columns to the market DataFrame: `supertrend`, `supertrend_dir`, `supertrend_up`, and `supertrend_down`.

The Supertrend indicator is a path-dependent, state-machine indicator: each bar's output depends on the previous bar's *already-resolved* output value (not just raw input values). Specifically:

- Each bar's `final_upper` and `final_lower` bands are ratcheted: they only tighten, never widen, unless the previous close price has crossed through the band (which resets it). The ratchet depends on the resolved band value from bar `i-1`, not the basic band.
- The active line (upper or lower) persists until price crosses through it. Which line is active is determined by the previous resolved `supertrend` value, which itself depends on the previous direction state.

This path dependency is the defining algorithmic constraint. Any correct algorithm must resolve bar `i` using the finalized state of bar `i-1` before processing bar `i`. This is a strict sequential dependency — it is not decomposable or parallelizable across bars.

The function also optionally pre-smooths the price series using a Hull Moving Average (HMA) before computing the indicator bands, to reduce whipsawing.

**Inputs**:
- `df`: pandas DataFrame, ~500 rows (n = 500 per `config.BARS_HISTORY`), OHLCV columns guaranteed present, sorted ascending by time.
- `atr_length`: int, default 10. Window for the simple ATR calculation.
- `atr_mult`: float, default 3.0. Band width multiplier.
- `source_col`: str, default `"close"`. Column used as the price input to HMA if enabled.
- `use_hma`: bool, default True. Whether to smooth price with HMA before band computation.
- `hma_length`: int, default 55. HMA window.

**Outputs**: The input DataFrame with four new columns appended. `supertrend_dir` is `1` (bullish), `-1` (bearish), or `0` (pre-warmup bars with no valid ATR).

**Constraints**:
- Called once per trading loop iteration (every 10 seconds in `main.py`) per unique timeframe — with 3 strategies sharing one timeframe, the `market_cache` deduplication means it is called once per loop, not 3 times.
- Also called once per GUI chart refresh from `gui_charts.py`, also with `market_cache` deduplication.
- Latency budget: `STRATEGY_ANALYSIS_TIMEOUT_SECONDS = 15s` for the full pipeline; `add_supertrend()` is one step in that pipeline.
- n = 500 rows, m (ATR/HMA window) = 10–55.

**Invariants**:
- DataFrame is always sorted ascending by time at call time.
- `high`, `low`, `close` columns are always present.
- ATR values for the first `atr_length - 1` rows are NaN — the loop must skip those rows gracefully.

**Clarity**: clear

---

## Current Algorithm

**Name**: Row-by-row sequential state machine (Python `for` loop over numpy arrays)

**Description**: The function allocates three raw numpy arrays (`final_upper`, `final_lower`, `supertrend`) of length n and one `direction` array. It then iterates over every row index `i` from 0 to n-1 with a Python `for` loop. At each step it reads `final_upper[i-1]`, `final_lower[i-1]`, and `supertrend[i-1]` (the already-computed state), applies the Supertrend ratchet and flip logic using branch conditions, and writes `final_upper[i]`, `final_lower[i]`, `supertrend[i]`, and `direction[i]`. Pre-warmup rows where ATR is NaN are skipped with `continue` and leave those array slots as NaN/0.

**Time**: O(n) worst and average — single pass, constant work per row.
**Space**: O(n) — four arrays of length n allocated upfront.

---

## Algorithm Candidates

### 1. Row-by-row sequential state machine — Python for loop (current)

- **Time**: O(n) | **Space**: O(n)
- **Verdict**: currently used — correct algorithm, suboptimal implementation
- **Assessment**: Correct algorithm. The sequential dependency between bar i and bar i-1 is real and unavoidable. A Python-level `for` loop over 500 elements is the only pure-Python way to express this correctly. However, the constant factor is high: each of the 500 iterations incurs Python interpreter overhead (bytecode dispatch, object method calls for `.iloc[i]`, attribute lookups). Estimated cost: ~500 × ~5–10 `pandas.Series.iloc` accesses = 2500–5000 interpreted object calls per invocation.

### 2. Numba JIT-compiled sequential state machine

- **Time**: O(n) | **Space**: O(n)
- **Verdict**: superior in throughput — not selected
- **Reason**: Numba compiles the same sequential logic to native machine code, eliminating Python interpreter overhead. The loop body becomes ~1–2 ns per iteration instead of ~1–5 µs. However, Numba is not in the project's current dependency set (requirements.txt uses only pandas, numpy, MetaTrader5, etc.). Adding Numba as a dependency for a 500-row loop that runs once every 10 seconds is not justified — the current loop completes in under 5 ms, well within the 15-second budget. The overhead of JIT compilation on first call also erases any per-call benefit on short series.

### 3. Vectorized prefix-scan / NumPy cumulative approach

- **Time**: O(n) amortized | **Space**: O(n)
- **Verdict**: eliminated — not applicable to this problem class
- **Reason**: The Supertrend ratchet is not a simple running min/max or cumulative sum. Each step's output depends on the *resolved* output of the previous step, creating a genuine recurrence relation: `final_upper[i] = f(final_upper[i-1], basic_upper[i], price[i-1])`. NumPy prefix operations (cumsum, maximum.accumulate, etc.) cannot encode this three-way conditional recurrence — the ratchet resets on a condition that itself depends on the previously ratcheted value. Any vectorized prefix scan over `basic_upper` without the ratchet would produce wrong results on bars where the basic band is wider than the previous ratcheted band. This candidate is eliminated on correctness grounds, not just performance.

### 4. Cython extension

- **Time**: O(n) | **Space**: O(n)
- **Verdict**: inferior in practice — eliminated
- **Reason**: Same correctness profile as Numba. Cython requires a compilation step, a C extension toolchain, and is significantly harder to maintain. No benefit over the current approach for n=500, called every 10 seconds, within a 15-second budget.

### 5. pandas-ta / TA-Lib external library

- **Time**: O(n) | **Space**: O(n)
- **Verdict**: eliminated — interface mismatch
- **Reason**: pandas-ta provides a Supertrend implementation, but it does not support the HMA pre-smoothing path that is baked into this function's `use_hma=True` default. The project's custom `hull_moving_average()` feeding into the Supertrend price input is intentional and strategy-specific. Delegating to an external library would either remove this capability or require post-hoc patching of the library's internals. Additionally, this introduces a new dependency for no complexity reduction in the core loop.

---

## Finding

- [ ] **Correct algorithm, optimal implementation** — no change needed
- [x] **Correct algorithm, suboptimal implementation** — constant-factor improvements available
- [ ] **Wrong algorithm** — replacement required (see Optimal Approach)

The sequential state machine is the correct and only viable algorithm for this problem class. The implementation is correct. The suboptimality is in the constant factor: `pandas.Series.iloc[i]` is called inside the Python `for` loop repeatedly on `price`, `basic_upper`, `basic_lower`, and `atr`. Each `.iloc[i]` on a pandas Series is an interpreted Python object call, not a direct array index. Extracting these to raw numpy arrays before the loop and indexing into them with integer indexing (`arr[i]`) eliminates the pandas overhead without changing the algorithm.

---

## Constant-Factor Analysis

- **Line 183**: `for i in range(len(df)):` — Python interpreter loop over 500 iterations. Each iteration incurs full CPython bytecode dispatch overhead. At ~1–5 µs per iteration, total loop cost is ~0.5–2.5 ms. Not catastrophic at 500 rows and 10-second intervals, but it is the dominant cost in this function.

- **Lines 184, 200, 202–211**: `atr.iloc[i]`, `price.iloc[i]`, `basic_upper.iloc[i]`, `basic_lower.iloc[i]` — all are pandas Series `.iloc` accesses inside the loop. `.iloc` on a Series goes through `_LocIndexer.__getitem__`, bounds validation, and dtype dispatch before returning a Python scalar. For 500 iterations with 4–5 `.iloc` calls each, this is 2000–2500 interpreted object calls per `add_supertrend()` invocation. These should be converted to numpy arrays via `.to_numpy()` before entering the loop, making each access a simple `arr[i]` C-level array read.

- **Lines 157–161**: ATR computation uses `pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)` — this constructs a temporary 500×3 DataFrame just to compute an element-wise maximum. `np.maximum(np.maximum(hl, hc), lc)` achieves the same result with no DataFrame allocation.

- **Line 152**: `df = df.copy()` — allocates a full copy of the DataFrame at entry. This is standard defensive practice for a function that mutates and returns; it is correct. No change recommended.

- **Lines 177–179**: Pre-allocation of `final_upper`, `final_lower`, `supertrend` as `np.full(len(df), np.nan)` is correct and idiomatic.

- **Lines 240–241**: `np.where(df['supertrend_dir'] == 1, ...)` — vectorized assignment of `supertrend_up` and `supertrend_down`. These are already optimal.

### Impact Estimate

Called once per 10-second trading loop iteration (via `market_cache` deduplication, so 1 call per timeframe group, not 1 per strategy). The `.iloc`-in-loop pattern costs roughly 1–3 ms per call at n=500 with CPython overhead. This is well within the 15-second budget and would not cause observable latency in production at current n. Improvement is available but not urgent.

---

## Optimal Approach

### Algorithm

Same algorithm: sequential state machine, O(n) time, O(n) space. No algorithm change required.

### Pseudocode

The only change is to extract all pandas Series used inside the loop to raw numpy arrays before entering the loop, and to replace the `pd.concat` ATR construction with element-wise numpy operations.

```
function add_supertrend(df, atr_length, atr_mult, source_col, use_hma, hma_length):
    df = df.copy()

    # ATR computation — avoid pd.concat temporary DataFrame
    atr_col = f"atr_st_{atr_length}"
    if atr_col not in df.columns or df[atr_col].isna().all():
        hl  = (df['high'] - df['low']).to_numpy()
        hc  = (df['high'] - df['close'].shift()).abs().to_numpy()
        lc  = (df['low']  - df['close'].shift()).abs().to_numpy()
        tr_arr = np.maximum(np.maximum(hl, hc), lc)    # no temporary DataFrame
        tr_series = pd.Series(tr_arr, index=df.index)
        df[atr_col] = tr_series.rolling(window=atr_length).mean()

    atr = df[atr_col]

    source = df[source_col] if source_col in df.columns else df['close']
    if use_hma:
        df['hma'] = hull_moving_average(source, hma_length)
        price_series = df['hma']
    else:
        price_series = source

    hl2 = (df['high'] + df['low']) / 2
    basic_upper_series = hl2 + (atr_mult * atr)
    basic_lower_series = hl2 - (atr_mult * atr)

    # Extract to numpy BEFORE the loop — eliminates .iloc overhead
    price_arr        = price_series.to_numpy()
    basic_upper_arr  = basic_upper_series.to_numpy()
    basic_lower_arr  = basic_lower_series.to_numpy()
    atr_arr          = atr.to_numpy()
    n                = len(df)

    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    supertrend  = np.full(n, np.nan)
    direction   = np.zeros(n)

    for i in range(n):
        if np.isnan(atr_arr[i]):       # plain numpy scalar check, no .iloc
            continue

        if i == 0:
            final_upper[i] = basic_upper_arr[i]
            final_lower[i] = basic_lower_arr[i]
            continue

        prev_fu = final_upper[i - 1] if not np.isnan(final_upper[i - 1]) else basic_upper_arr[i - 1]
        prev_fl = final_lower[i - 1] if not np.isnan(final_lower[i - 1]) else basic_lower_arr[i - 1]
        prev_price = price_arr[i - 1]

        if basic_upper_arr[i] < prev_fu or prev_price > prev_fu:
            final_upper[i] = basic_upper_arr[i]
        else:
            final_upper[i] = prev_fu

        if basic_lower_arr[i] > prev_fl or prev_price < prev_fl:
            final_lower[i] = basic_lower_arr[i]
        else:
            final_lower[i] = prev_fl

        prev_super = supertrend[i - 1]
        if np.isnan(prev_super):
            if price_arr[i] >= final_lower[i]:
                supertrend[i] = final_lower[i]
                direction[i] = 1
            else:
                supertrend[i] = final_upper[i]
                direction[i] = -1
            continue

        if prev_super == prev_fu:
            if price_arr[i] <= final_upper[i]:
                supertrend[i] = final_upper[i]
                direction[i] = -1
            else:
                supertrend[i] = final_lower[i]
                direction[i] = 1
        else:
            if price_arr[i] >= final_lower[i]:
                supertrend[i] = final_lower[i]
                direction[i] = 1
            else:
                supertrend[i] = final_upper[i]
                direction[i] = -1

    df['supertrend']     = supertrend
    df['supertrend_dir'] = direction
    df['supertrend_up']  = np.where(direction == 1,  supertrend, np.nan)
    df['supertrend_down'] = np.where(direction == -1, supertrend, np.nan)
    return df
```

### Trade-offs

| Trade-off | Detail |
|-----------|--------|
| Readability | Marginally worse — `.iloc[i]` reads as "pandas access" which is familiar; `arr[i]` is equivalent but requires understanding the `.to_numpy()` extraction above. Comment the extraction step. |
| Correctness risk | Low. The numpy scalar comparisons (`np.isnan`, `arr[i]`) are semantically identical to the pandas equivalents at this dtype (float64). NaN propagation behavior is unchanged. |
| New dependencies | None — numpy is already a direct dependency. |
| Numerical precision | No change. The computation is identical; only the Python object path to reach each value is shorter. |
| ATR change | Replacing `pd.concat(...).max(axis=1)` with `np.maximum(np.maximum(hl, hc), lc)` produces bitwise-identical float64 results. The only difference is memory: no 500×3 temporary DataFrame is allocated. |
