# Pre-Implementation: ADX/DI Indicator + Crossover Condition Model

**By**: Daniel
**Date**: 2026-04-06
**Task**: TASK-019
**Status**: ready

---

## Formal Problem Statement

**Problem A — ADX/+DI/-DI column computation**

**Input**: A pandas DataFrame with columns `high`, `low`, `close` (float), sorted ascending by time. n=500 rows typical; period configurable by user (integer ≥ 2, default 14).

**Output**: Five new float/int columns appended to the DataFrame in `prepare_dataframe`:
- `adx_<period>` — Average Directional Index, range [0, 100]
- `plus_di_<period>` — Positive Directional Indicator, range [0, 100]
- `minus_di_<period>` — Negative Directional Indicator, range [0, 100]
- `plus_di_cross_<period>` — int (0/1): 1 on the candle where +DI first crossed above -DI, else 0
- `minus_di_cross_<period>` — int (0/1): 1 on the candle where -DI first crossed above +DI, else 0

**Constraints**:
- Wilder smoothing (EWM alpha=1/period) — matches existing `_atr()` and `_rsi()` implementations in `builder.py`
- Called once per strategy per market cycle (every 10s), n=500, inside `prepare_dataframe`
- Must tolerate NaN gracefully at the beginning of the Series (EWM with `min_periods=period`)
- All column names are snake_case with period suffix (consistent with catalogue convention)

**Invariants**:
- `high >= low` for every row (MT5 guarantee)
- DataFrame is sorted ascending by time (oldest row first)
- n ≥ 2 (caller's `len(df) < 3` guard in `get_last_signal` is the minimum contract)

**Clarity**: ✅ clear

---

**Problem B — Crossover condition representation**

**Input**: The user specifies "+DI crosses above -DI" as a buy trigger in the Builder GUI.

**Output**: A mechanism for the Builder to represent and emit this condition that:
1. Requires no changes to the ConditionNode schema (TASK-014b)
2. Works correctly in both `get_last_signal` (scalar, `df.iloc[-2]`) and `compute_signals` (vectorized)
3. Is implementable by Felix in TASK-025 without touching the emitter

**Constraints**:
- ConditionNode schema (TASK-014b) is frozen — must not be extended if avoidable
- The current `emit_condition` only references `df.iloc[-2]["col"]` — no multi-row access
- The vectorized emitter uses `out["col"]` as a pandas Series — no `.shift()` support today

**Clarity**: ✅ clear

---

## Candidate Algorithms — ADX/DI Computation

### 1. Wilder EWM vectorized (`ewm(alpha=1/period, adjust=False)`)
- **Description**: Compute TR, +DM, -DM via vectorized pandas operations. Apply Wilder smoothing using `pandas.Series.ewm(alpha=1/period, min_periods=period, adjust=False).mean()`. Compute +DI, -DI, DX, ADX from smoothed values.
- **Time**: O(n) — fully vectorized; single pass per ewm call; 6 ewm calls total
- **Space**: O(n) — intermediate series; no retained state between calls
- **Verdict**: selected
- **Reason**: Matches how `_atr()` and `_rsi()` in `builder.py` already implement Wilder smoothing. Consistent numerical behavior. Fully vectorized. With n=500, 6×O(n) ewm calls complete in well under 1ms.

### 2. Explicit Python loop (recursive Wilder formula)
- **Description**: Implement `smma[i] = smma[i-1] × (period-1)/period + value[i] / period` in a Python for-loop over n=500 rows.
- **Time**: O(n) — but with n=500 Python interpreter dispatches per loop
- **Space**: O(n)
- **Verdict**: eliminated
- **Reason**: Mathematically equivalent to Candidate 1 but ~100× slower due to Python-level loop. The ewm vectorized approach is the established pattern in this codebase. Python loops over n=500 are a known anti-pattern in the existing code review context.

### 3. RMA via pandas rolling
- **Description**: Approximate Wilder smoothing as `rolling(period).mean()` with `min_periods=1`.
- **Verdict**: eliminated
- **Reason**: Not the Wilder formula. Produces different numerical output. All other indicators in this codebase use exact Wilder EWM — inconsistency would confuse both users and the strategy author.

**Winner**: Candidate 1 — Wilder EWM vectorized.

---

## Candidate Algorithms — Crossover Condition Model

The crossover `+DI crosses above -DI` is equivalent to:
- Current candle (iloc[-2]): `plus_di_14 > minus_di_14`
- Previous candle (iloc[-3]): `plus_di_14 <= minus_di_14`

The current emitter only knows `df.iloc[-2]`. Three options:

### Option A: New `"crossover"` ConditionNode type
- **Description**: Add `{"type": "crossover", "above": "plus_di_14", "below": "minus_di_14"}` to the schema. Extend `emit_condition`, `_emit_vectorized_condition`, `_validate_condition_node`, `_collect_leaf_columns` in `builder.py`.
- **Changes required**: ConditionNode schema (TASK-014b spec), validator (5 lines), scalar emitter, vectorized emitter, leaf column collector — 5 distinct locations in `builder.py`
- **Verdict**: viable but eliminated
- **Reason**: High schema-change cost for a problem already solvable at the data level. The ConditionNode schema is settled and tested. Extending it requires re-review (another Daniel pass). The `get_last_signal` guard (`len(df) < 3`) would also need changing to `len(df) < 4` since `df.iloc[-3]` would be needed — a subtle correctness risk.

### Option B: Pre-computed boolean flag column in `prepare_dataframe` ← SELECTED
- **Description**: `prepare_dataframe` computes a crossover column using vectorized `.shift(1)`:
  ```
  plus_di_cross_14 = ((plus_di_14 > minus_di_14) & (plus_di_14.shift(1) <= minus_di_14.shift(1))).astype(int)
  ```
  The condition in the tree is then a plain leaf: `{"type": "condition", "left": "plus_di_cross_14", "op": ">", "right": 0}`, which emits as `df.iloc[-2]["plus_di_cross_14"] > 0`.
- **Changes required**: None to ConditionNode schema, validator, or emitters. Only `prepare_dataframe` code generation and the `VALID_INDICATOR_IDS` / column set in `builder.py`.
- **Verdict**: selected
- **Reason**: See full justification below.

### Option C: Extend ConditionLeaf with a `row` offset field
- **Description**: Add `"row": -3` to ConditionLeaf. The emitter translates `row=-3` to `df.iloc[-3]`. The vectorized emitter translates `row=-3` to `.shift(1)`.
- **Changes required**: ConditionLeaf schema, validator, both emitters, the `get_last_signal` guard — 4 locations. The `row → shift` mapping is non-trivial in the vectorized emitter.
- **Verdict**: eliminated
- **Reason**: More complex than Option A while providing less semantic clarity. Forces the user to construct two explicit conditions for one crossover concept. The row-to-shift mapping is error-prone to implement and test in the vectorized path.

---

## Selected Algorithms

**ADX computation**: Wilder EWM vectorized (Candidate 1)

**Crossover model**: Pre-computed boolean column in `prepare_dataframe` (Option B)

**Justification for Option B**:

1. **Zero schema impact**: The ConditionNode model (TASK-014b) is complete and frozen. It has been validated and implemented in `builder.py`. Touching it requires re-review and re-testing. Option B adds no fields, no node types, no emitter changes.

2. **Conceptual correctness**: A crossover IS a per-candle boolean event — "did the cross happen on this candle?" This is exactly the semantics of a pre-computed column. It is a derived state, not a multi-row query at evaluation time. `supertrend_dir`, `tci_hist` are the same pattern: pre-computed state columns used as condition operands.

3. **Vectorized path works immediately**: `compute_signals` uses `_emit_vectorized_condition`, which produces `out["plus_di_cross_14"] > 0` — a standard boolean Series comparison. No `.shift()` plumbing needed in the emitter.

4. **NaN safety**: `.shift(1)` in `prepare_dataframe` produces NaN at row 0, which `.astype(int)` coerces to 0. The crossover column is always safe to read at `df.iloc[-2]` regardless of DataFrame length (as long as ≥ 2 rows — satisfied by the existing `len(df) < 3` guard).

5. **Lookback correctness**: The crossover column requires two consecutive valid `plus_di` values. Since `plus_di` requires `2*period - 1` rows for the first valid value (row 27 for period=14), the crossover column produces its first valid 1 no earlier than row 28. With n=500 rows, `df.iloc[-2]` is always in the stable zone.

---

## ADX Formal Specification

### Formulas (Wilder method, period = P)

```
# Per-row inputs (vectorized; subscript i is current row, i-1 is previous row)

TR[i]      = max(High[i] - Low[i],
                 |High[i] - Close[i-1]|,
                 |Low[i]  - Close[i-1]|)

up_move[i]   = High[i] - High[i-1]
down_move[i] = Low[i-1] - Low[i]

+DM[i] = up_move[i]   if (up_move[i] > down_move[i]) and (up_move[i] > 0)   else 0
-DM[i] = down_move[i] if (down_move[i] > up_move[i]) and (down_move[i] > 0) else 0

# Wilder smoothing: EWM(alpha=1/P, min_periods=P, adjust=False)
ATR_w[i] = EWM(TR,  alpha=1/P)[i]
+DM_s[i] = EWM(+DM, alpha=1/P)[i]
-DM_s[i] = EWM(-DM, alpha=1/P)[i]

+DI[i] = 100 × +DM_s[i] / ATR_w[i]          (ATR_w == 0 → NaN)
-DI[i] = 100 × -DM_s[i] / ATR_w[i]          (ATR_w == 0 → NaN)

DX[i]  = 100 × |+DI[i] - -DI[i]| / (+DI[i] + -DI[i])   (sum == 0 → NaN)

ADX[i] = EWM(DX, alpha=1/P)[i]

# Crossover flags
+DI_cross[i] = 1 if (+DI[i] > -DI[i]) and (+DI[i-1] <= -DI[i-1])  else 0
-DI_cross[i] = 1 if (-DI[i] > +DI[i]) and (-DI[i-1] <= +DI[i-1])  else 0
```

### Column naming convention (canonical)

| Column | Naming pattern | Example (P=14) |
|--------|---------------|----------------|
| ADX | `adx_<period>` | `adx_14` |
| +DI | `plus_di_<period>` | `plus_di_14` |
| -DI | `minus_di_<period>` | `minus_di_14` |
| +DI crossover flag | `plus_di_cross_<period>` | `plus_di_cross_14` |
| -DI crossover flag | `minus_di_cross_<period>` | `minus_di_cross_14` |

**Rationale for naming**:
- `adx_14` — parallel to `rsi_14`, `atr_14`, `ema_14` (consistent pattern across catalogue)
- `plus_di_14` / `minus_di_14` — unambiguous, readable, no special characters
- `plus_di_cross_14` — clearly derived from `plus_di_14`; the `_cross_` infix distinguishes it as a crossover flag, not a raw indicator value

### Lookback requirement

| Metric | Formula | Value (P=14) |
|--------|---------|-------------|
| First non-NaN +DI / -DI | `min_periods = P` | Row 14 (0-indexed) |
| First non-NaN ADX | `2P - 1` | Row 27 (0-indexed, i.e., 28th candle) |
| First valid crossover | `2P` | Row 28 (0-indexed, i.e., 29th candle) |
| Recommended minimum for stability | `3P` | 42 candles |
| Available in production | n=500 | ✅ well within safe zone |

**Note on `min_periods`**: `ewm(..., min_periods=period)` produces NaN for the first `period-1` rows. The first non-NaN +DI value is at index `period-1` (14th row, 0-indexed). ADX is EWM of DX, also with `min_periods=period`, so the first non-NaN ADX is at index `2*(period-1)` = 26 (0-indexed). With 500 rows and `df.iloc[-2]` being row 498, this is always in the stable zone.

---

## Pseudocode Spec

### `_adx_di(high, low, close, period)` — pure computation, returns tuple of 5 Series

Called inside `prepare_dataframe`. The coding agent translates this pseudocode to Python using pandas. No algorithmic decisions left to the coding agent.

```
function _adx_di(high: Series, low: Series, close: Series, period: int)
        -> (adx: Series, plus_di: Series, minus_di: Series,
            plus_di_cross: Series, minus_di_cross: Series):

    # Step 1: True Range (vectorized max of 3 components)
    prev_close = close.shift(1)
    hl         = high - low
    hc         = (high - prev_close).abs()
    lc         = (low  - prev_close).abs()
    tr         = pd.concat([hl, hc, lc], axis=1).max(axis=1)

    # Step 2: Directional Movement components
    up_move   = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm  = pd.Series(0.0, index=high.index)
    minus_dm = pd.Series(0.0, index=high.index)
    plus_dm  = np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm  = pd.Series(plus_dm,  index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    # Step 3: Wilder smoothing (alpha = 1/period)
    alpha = 1.0 / period
    ema_kwargs = {"alpha": alpha, "min_periods": period, "adjust": False}
    atr_w      = tr.ewm(**ema_kwargs).mean()
    plus_dm_s  = plus_dm.ewm(**ema_kwargs).mean()
    minus_dm_s = minus_dm.ewm(**ema_kwargs).mean()

    # Step 4: +DI, -DI  (protect against zero ATR)
    safe_atr  = atr_w.replace(0.0, float("nan"))
    plus_di   = 100.0 * plus_dm_s  / safe_atr
    minus_di  = 100.0 * minus_dm_s / safe_atr

    # Step 5: DX, ADX
    di_sum = (plus_di + minus_di).replace(0.0, float("nan"))
    dx     = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx    = dx.ewm(**ema_kwargs).mean()

    # Step 6: Crossover flags (boolean → int)
    plus_di_prev  = plus_di.shift(1)
    minus_di_prev = minus_di.shift(1)
    plus_cross  = ((plus_di  > minus_di) & (plus_di_prev  <= minus_di_prev)).astype(int)
    minus_cross = ((minus_di > plus_di)  & (minus_di_prev <= plus_di_prev )).astype(int)

    return adx, plus_di, minus_di, plus_cross, minus_cross
```

### Integration into `_emit_indicator_computation_block` (builder.py)

When `ind["id"] == "ADX_DI"` and `period = ind["params"]["period"]`:

```
emit lines:
    adx_{period}, plus_di_{period}, minus_di_{period}, \
        plus_di_cross_{period}, minus_di_cross_{period} = \
        _adx_di(high, low, close, {period})
```

### Integration into `_emit_prepare_dataframe` column assignment

For the ADX_DI indicator, the assignment block assigns all 5 columns:

```
    out["adx_{period}"]            = adx_{period}
    out["plus_di_{period}"]        = plus_di_{period}
    out["minus_di_{period}"]       = minus_di_{period}
    out["plus_di_cross_{period}"]  = plus_di_cross_{period}
    out["minus_di_cross_{period}"] = minus_di_cross_{period}
```

### What the Builder generates for the +DI crossover condition

The complete buy condition for the strategy in `primeraEstrategia.md`:

```json
{
  "type": "AND",
  "children": [
    {"type": "condition", "left": "adx_14", "op": ">", "right": 25},
    {"type": "condition", "left": "plus_di_cross_14", "op": ">", "right": 0}
  ]
}
```

`emit_condition` produces (unchanged, no modifications needed):
```python
(df.iloc[-2]["adx_14"] > 25 and df.iloc[-2]["plus_di_cross_14"] > 0)
```

`_emit_vectorized_condition` produces (unchanged):
```python
((out["adx_14"] > 25) & (out["plus_di_cross_14"] > 0))
```

Both are correct and safe. No emitter changes required.

---

## Changes Required in `builder.py` (for TASK-025)

Felix must make the following additions to `strategies/builder.py`. **No existing logic is modified** — only additions:

### 1. Add `"ADX_DI"` to `VALID_INDICATOR_IDS`

```python
VALID_INDICATOR_IDS = {
    "EMA", "RSI", "BB", "DONCHIAN", "ATR", "VWAP",
    "VOLUME_RATIO", "SMA", "HMA", "SUPERTREND", "TCI",
    "ADX_DI",  # ← add this
}
```

### 2. Add `_TEMPLATE_ADX_DI` helper function template

```python
_TEMPLATE_ADX_DI = """\
def _adx_di(high: pd.Series, low: pd.Series, close: pd.Series, length: int):
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low,
         (high - prev_close).abs(),
         (low  - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    up_move   = high - high.shift(1)
    down_move = low.shift(1) - low
    import numpy as _np
    plus_dm  = pd.Series(_np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0), index=high.index)
    minus_dm = pd.Series(_np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    alpha = 1.0 / length
    kw = {"alpha": alpha, "min_periods": length, "adjust": False}
    atr_w     = tr.ewm(**kw).mean()
    safe_atr  = atr_w.replace(0.0, float("nan"))
    plus_di   = 100.0 * plus_dm.ewm(**kw).mean()  / safe_atr
    minus_di  = 100.0 * minus_dm.ewm(**kw).mean() / safe_atr
    di_sum    = (plus_di + minus_di).replace(0.0, float("nan"))
    dx        = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx       = dx.ewm(**kw).mean()
    pprev, mprev = plus_di.shift(1), minus_di.shift(1)
    plus_cross  = ((plus_di  > minus_di) & (pprev <= mprev)).astype(int)
    minus_cross = ((minus_di > plus_di)  & (mprev <= pprev)).astype(int)
    return adx, plus_di, minus_di, plus_cross, minus_cross"""
```

**Note on numpy import**: The `_adx_di` helper uses `numpy.where`. The generated strategy files do not import numpy at the module level (builder.py currently only imports pandas). The numpy import is placed as a local import inside `_adx_di` to keep the generated file self-contained without adding a top-level `import numpy` to every strategy. Felix must ensure this local import does not conflict with any future module-level numpy import added by builder.py.

**Alternative** if a module-level numpy import is preferred (simpler): Add `import numpy as np` to the generated file header in `_emit_docstring` or as a new section, and use `np.where` in the template. Either approach is acceptable — the local import is chosen here to minimize impact on existing generated strategies.

### 3. Register ADX_DI in `_emit_helper_functions`

```python
if "ADX_DI" in custom_ids:
    blocks.append(_TEMPLATE_ADX_DI)
```

### 4. Add computation block in `_emit_indicator_computation_block`

```python
elif ind_id == "ADX_DI":
    period = int(p["period"])
    return [
        f"    adx_{period}, plus_di_{period}, minus_di_{period}, "
        f"plus_di_cross_{period}, minus_di_cross_{period} = "
        f"_adx_di(high, low, close, {period})",
    ]
```

### 5. Add `needs_high_low = True` for ADX_DI in `generate_strategy_file`

ADX_DI requires `high` and `low` (in addition to `close`). The existing `needs_high_low` check:

```python
needs_high_low = any(ind["id"] in ("DONCHIAN", "ATR", "VWAP") for ind in custom_indicators)
```

Must be extended to:
```python
needs_high_low = any(ind["id"] in ("DONCHIAN", "ATR", "VWAP", "ADX_DI") for ind in custom_indicators)
```

And `needs_close` for ADX_DI (close is used for TR):
```python
needs_close = any(
    ind["id"] in ("EMA", "RSI", "BB", "ATR", "VWAP", "VOLUME_RATIO", "SMA", "ADX_DI")
    for ind in custom_indicators
)
```

### 6. Add module constants in `_emit_module_constants`

```python
elif ind_id == "ADX_DI":
    period = int(p["period"])
    lines.append(f"ADX_DI_{period}_PERIOD = {period}")
```

### 7. Add Data Window entries in `_emit_data_window_fields`

```python
elif ind_id == "ADX_DI":
    period = int(p["period"])
    entries.append(
        f'{{"key": "adx_{period}", "label": "ADX ({period})", "format": "number", "section": "ADX"}}'
    )
    entries.append(
        f'{{"key": "plus_di_{period}", "label": "+DI ({period})", "format": "number", "section": "ADX"}}'
    )
    entries.append(
        f'{{"key": "minus_di_{period}", "label": "-DI ({period})", "format": "number", "section": "ADX"}}'
    )
    entries.append(
        f'{{"key": "plus_di_cross_{period}", "label": "+DI Cross ({period})", "format": "int", "section": "ADX"}}'
    )
    entries.append(
        f'{{"key": "minus_di_cross_{period}", "label": "-DI Cross ({period})", "format": "int", "section": "ADX"}}'
    )
```

---

## Catalogue Entry for TASK-014a Update

The following entry must be appended to Section 3 of `agents/specs/TASK-014a-indicator-catalogue.md`:

### 3.13 ADX_DI — Average Directional Index + Directional Indicators

**User-visible name**: ADX + DI
**Configurable parameter**: Period (integer ≥ 2, default 14)
**Formula**: Wilder smoothing (EWM alpha=1/period) — same method as ATR (EWM) and RSI

**Columns produced** (5 total):

| Column | Formula/Meaning | Range |
|--------|----------------|-------|
| `adx_<period>` | Average Directional Index — trend strength | [0, 100] |
| `plus_di_<period>` | +Directional Indicator — upward movement strength | [0, 100] |
| `minus_di_<period>` | −Directional Indicator — downward movement strength | [0, 100] |
| `plus_di_cross_<period>` | 1 on candle where +DI crossed above -DI, else 0 | {0, 1} |
| `minus_di_cross_<period>` | 1 on candle where -DI crossed above +DI, else 0 | {0, 1} |

**Inputs**: `high`, `low`, `close`
**Source**: Requires `prepare_dataframe`. Helper function `_adx_di(high, low, close, length)`.

**Indicator ID** (for `config["indicators"][*]["id"]`): `"ADX_DI"`

**Lookback**: First reliable ADX at row `2*period - 1` (row 27 for period=14). Crossover columns valid from row `2*period`. With n=500 rows, always in stable zone.

**Builder note**: The crossover columns (`plus_di_cross_<period>`, `minus_di_cross_<period>`) are first-class condition operands. The user can use `plus_di_cross_14 > 0` as a leaf condition to detect the +DI/-DI cross. This is the recommended representation for the `primeraEstrategia.md` buy trigger.

---

## Strategy JSON Config for `primeraEstrategia.md`

For reference, the indicator entry for ADX_DI in a StrategyConfig:

```json
{
  "id": "ADX_DI",
  "pre_computed": false,
  "params": {"period": 14},
  "columns": ["adx_14", "plus_di_14", "minus_di_14", "plus_di_cross_14", "minus_di_cross_14"]
}
```

The `columns` list is what the validator uses to build the available column set. All 5 columns must be listed so that condition leaves referencing them pass validation.

---

## Summary for Felix (TASK-025)

Felix implements the following in `strategies/builder.py` — all additions, no modifications to existing code:

| Change | Location | Type |
|--------|----------|------|
| Add `"ADX_DI"` | `VALID_INDICATOR_IDS` | one-line addition to set |
| Add `_TEMPLATE_ADX_DI` | module level, after `_TEMPLATE_ATR` | new string constant |
| Register template | `_emit_helper_functions` | one if-branch |
| Add computation block | `_emit_indicator_computation_block` | one elif-branch |
| Extend `needs_high_low` | `generate_strategy_file` | add `"ADX_DI"` to tuple |
| Extend `needs_close` | `generate_strategy_file` | add `"ADX_DI"` to tuple |
| Add module constant | `_emit_module_constants` | one elif-branch |
| Add Data Window entries | `_emit_data_window_fields` | one elif-branch |

**No changes to**: `emit_condition`, `_emit_vectorized_condition`, `_validate_condition_node`, `_collect_leaf_columns`, `ConditionNode` schema, or any other existing function.
