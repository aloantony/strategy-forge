# Pre-Implementation: Strategy Data Model Schema, Generator Pseudocode, and Persistence Spec

**By**: Daniel
**Date**: 2026-04-04
**Task**: TASK-014c
**Status**: ready

**Upstream dependencies consumed**:
- `agents/specs/TASK-014a-indicator-catalogue.md` — canonical column names, indicator params, valid timeframes
- `agents/specs/TASK-014b-condition-tree-model.md` — `ConditionNode` schema, `emit_condition` pseudocode (scalar), edge cases EC-1 through EC-8

---

## 1. Formal Problem Statement

**Input**: A validated strategy configuration object — the data that the GUI form serializes to JSON when the user presses "Save". Contains strategy identity, timeframe, list of selected indicators with parameters, and two condition trees (buy and sell).

**Output A**: A complete, syntactically valid `strategies/strategy_<name>.py` file that implements the strategy interface (`get_last_signal`, `prepare_dataframe`, `compute_signals`, `get_last_signal_payload`, `DATA_WINDOW_FIELDS`, `TIMEFRAME`, `MAGIC_NUMBER`).

**Output B**: A companion `strategies/strategy_<name>.json` file containing the original configuration object verbatim — the round-trip source for future edits.

**Constraints**:
- Generated `.py` must obey the isolation rule: no imports from `config`, `trading`, or `gui_charts`
- Only `import pandas as pd` is allowed (plus `import json` if needed internally — but the generated strategy needs none)
- Generated strategy must return `"buy"`, `"sell"`, or `"none"` for any valid DataFrame input without raising exceptions
- The generator runs at code-generation time (user presses Save) — performance budget is unlimited (single write per user action)
- The companion `.json` must be round-trippable: loading it and calling the generator again must produce byte-for-byte identical `.py` output

**Invariants**:
- The config object has already been validated before the generator is called — the generator assumes pre-validated input
- All column names in the condition trees exist in the indicator catalogue or the always-available set
- `name` matches `^[a-z][a-z0-9_]*$`
- `magic_number` is already assigned (either freshly generated or preserved from the previous version)

**Clarity**: ✅ clear

---

## 2. Top-Level Strategy Configuration Schema

### 2.1 JSON Schema (normative)

This is the schema for the companion `.json` file and the payload the GUI sends on Save.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema",
  "title": "StrategyConfig",
  "type": "object",
  "required": ["schema_version", "name", "display_name", "timeframe",
               "magic_number", "indicators", "buy_condition", "sell_condition"],
  "additionalProperties": false,
  "properties": {

    "schema_version": {
      "type": "integer",
      "const": 1,
      "description": "Schema version integer. Increment when fields are added or changed."
    },

    "name": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9_]*$",
      "description": "Machine-readable name. Determines filenames: strategy_<name>.py and strategy_<name>.json"
    },

    "display_name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 80,
      "description": "User-visible name shown in the GUI strategy list"
    },

    "description": {
      "type": "string",
      "maxLength": 500,
      "default": "",
      "description": "Optional free-text description of the strategy logic (used in docstring)"
    },

    "timeframe": {
      "type": "string",
      "enum": ["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
      "description": "MT5 timeframe string. Emitted as TIMEFRAME = \"<value>\" in the generated .py"
    },

    "magic_number": {
      "type": "integer",
      "minimum": 10000,
      "maximum": 99999,
      "description": "MT5 magic number for order tracking. Assigned at first create; preserved unchanged on all subsequent edits."
    },

    "indicators": {
      "type": "array",
      "items": { "$ref": "#/$defs/IndicatorConfig" },
      "description": "Ordered list of indicator instances selected by the user. Order determines the emission order in prepare_dataframe."
    },

    "buy_condition": {
      "$ref": "#/$defs/ConditionNode",
      "description": "Root of the buy condition tree"
    },

    "sell_condition": {
      "$ref": "#/$defs/ConditionNode",
      "description": "Root of the sell condition tree"
    }
  },

  "$defs": {

    "IndicatorConfig": {
      "type": "object",
      "required": ["id", "params", "columns", "pre_computed"],
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string",
          "enum": ["EMA", "RSI", "BB", "DONCHIAN", "ATR", "VWAP",
                   "VOLUME_RATIO", "SMA", "HMA", "SUPERTREND", "TCI"],
          "description": "Indicator type identifier"
        },
        "params": {
          "type": "object",
          "description": "Indicator parameters. Indicator-specific — see Section 2.2."
        },
        "columns": {
          "type": "array",
          "items": { "type": "string" },
          "minItems": 1,
          "description": "Exact DataFrame column names this instance produces. Authoritative — generator uses this list directly."
        },
        "pre_computed": {
          "type": "boolean",
          "description": "True = columns are already present from data_feed; prepare_dataframe skips this indicator."
        }
      }
    },

    "ConditionNode": {
      "oneOf": [
        { "$ref": "#/$defs/ConditionLeaf" },
        { "$ref": "#/$defs/ConditionGroup" }
      ]
    },

    "ConditionLeaf": {
      "type": "object",
      "required": ["type", "left", "op", "right"],
      "additionalProperties": false,
      "properties": {
        "type":  { "const": "condition" },
        "left":  { "type": "string" },
        "op":    { "enum": ["<", ">", "<=", ">=", "==", "!="] },
        "right": { "oneOf": [{ "type": "number" }, { "type": "string" }] }
      }
    },

    "ConditionGroup": {
      "type": "object",
      "required": ["type", "children"],
      "additionalProperties": false,
      "properties": {
        "type":     { "enum": ["AND", "OR"] },
        "children": {
          "type": "array",
          "items": { "$ref": "#/$defs/ConditionNode" },
          "minItems": 2
        }
      }
    }
  }
}
```

### 2.2 Indicator params schemas (per `id`)

| `id` | `params` fields | `columns` produced | `pre_computed` |
|------|-----------------|--------------------|----------------|
| `EMA` | `{"period": int ≥ 1}` | `["ema_<period>"]` | `false` |
| `RSI` | `{"period": int ≥ 2}` | `["rsi_<period>"]` | `false` |
| `BB` | `{"period": int ≥ 2, "multiplier": float > 0}` | `["bb_basis_<period>", "bb_upper_<period>", "bb_lower_<period>", "bb_width_pct_<period>"]` | `false` |
| `DONCHIAN` | `{"period": int ≥ 2}` | `["donchian_high_<period>", "donchian_low_<period>", "donchian_mid_<period>"]` | `false` |
| `ATR` | `{"period": int ≥ 1}` | `["atr_<period>", "atr_pct_<period>"]` | `false` |
| `VWAP` | `{}` | `["vwap"]` | `false` |
| `VOLUME_RATIO` | `{"lookback": int ≥ 2}` | `["volume_ratio_<lookback>"]` | `false` |
| `SMA` | `{"period": int ≥ 1}` | `["sma_<period>"]` | `false` |
| `HMA` | `{}` | `["hma"]` | `true` |
| `SUPERTREND` | `{}` | `["supertrend", "supertrend_dir", "supertrend_up", "supertrend_down"]` | `true` |
| `TCI` | `{}` | `["tci", "tci_signal", "tci_hist"]` | `true` |

**Column name rule**: All `<period>` and `<lookback>` substitutions use `int(params["period"])` — always an integer string, never a float (e.g., `ema_9` not `ema_9.0`). Column names in the `columns` array are stored as exact strings at GUI-time; the generator uses `ind["columns"]` directly and never re-derives names from `id + params`.

### 2.3 Canonical JSON example

A complete valid `StrategyConfig` for a strategy using EMA(9), EMA(21), RSI(14), and an OR-nested buy condition:

```json
{
  "schema_version": 1,
  "name": "ema_rsi_cross",
  "display_name": "EMA Cross + RSI Filter",
  "description": "Buy when fast EMA crosses above slow EMA and RSI is in momentum zone.",
  "timeframe": "H1",
  "magic_number": 47231,
  "indicators": [
    {
      "id": "EMA",
      "params": { "period": 9 },
      "columns": ["ema_9"],
      "pre_computed": false
    },
    {
      "id": "EMA",
      "params": { "period": 21 },
      "columns": ["ema_21"],
      "pre_computed": false
    },
    {
      "id": "RSI",
      "params": { "period": 14 },
      "columns": ["rsi_14"],
      "pre_computed": false
    }
  ],
  "buy_condition": {
    "type": "AND",
    "children": [
      {
        "type": "condition",
        "left": "ema_9",
        "op": ">",
        "right": "ema_21"
      },
      {
        "type": "condition",
        "left": "rsi_14",
        "op": ">",
        "right": 50
      }
    ]
  },
  "sell_condition": {
    "type": "AND",
    "children": [
      {
        "type": "condition",
        "left": "ema_9",
        "op": "<",
        "right": "ema_21"
      },
      {
        "type": "condition",
        "left": "rsi_14",
        "op": "<",
        "right": 50
      }
    ]
  }
}
```

---

## 3. Structure of the Generated `.py` File

The generated strategy module has nine sections. The table below identifies which are **fixed boilerplate** (identical across all generated strategies, no substitutions) vs. **parameterized** (contain substitutions from the config).

| # | Section | Type | Notes |
|---|---------|------|-------|
| 1 | Module docstring | Parameterized | `display_name`, `description`, `timeframe` |
| 2 | Import statement | Fixed boilerplate | Always exactly `import pandas as pd` |
| 3 | Module-level constants | Parameterized | `TIMEFRAME`, `MAGIC_NUMBER`, one constant per indicator parameter |
| 4 | `DATA_WINDOW_FIELDS` | Parameterized | One entry per indicator column + fixed signal entries |
| 5 | Helper functions | Conditionally boilerplate | `_numeric` always; `_rsi`, `_atr`, `_intraday_vwap`, `_volume_series` conditionally |
| 6 | `prepare_dataframe` | Parameterized (omitted if all pre-computed) | One computation block per non-pre-computed indicator |
| 7 | `compute_signals` | Parameterized | Buy/sell expressions from vectorized emitter |
| 8 | `get_last_signal_payload` | Parameterized | `display_name` in reason strings |
| 9 | `get_last_signal` | Fixed boilerplate | Always delegates to `get_last_signal_payload` |

### Fixed boilerplate sections (verbatim, no substitution)

**Section 2 — Import:**
```python
import pandas as pd
```

**Section 9 — `get_last_signal`:**
```python
def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    if df is None or len(df) < 3:
        return "none"
    if <buy_expr>:
        return "buy"
    elif <sell_expr>:
        return "sell"
    return "none"
```

Where `<buy_expr>` and `<sell_expr>` are the outputs of `emit_condition(buy_condition)` and `emit_condition(sell_condition)` from TASK-014b. These ARE substituted values, but the surrounding function shell is invariant. The function re-evaluates the condition tree directly (using `df.iloc[-2]`) rather than reading from `up_sig` — this makes `get_last_signal` self-contained and callable without prior `compute_signals`.

**Helper function bodies** (when emitted) are verbatim copies of the reference implementations confirmed in TASK-014a. Their internal logic is fixed boilerplate; only the decision of whether to emit them is parameterized.

---

## 4. Generator Pseudocode

### 4.1 Entry point: `generate_strategy_file`

```
function generate_strategy_file(config: dict, strategies_dir: Path, is_new: bool) -> Path:
    """
    Preconditions (enforced by validate_strategy_config before this is called):
      - config passes JSON schema validation
      - All condition tree column refs exist in config["indicators"] columns or always-available set
      - If is_new=True: neither strategy_<name>.py nor strategy_<name>.json exist
      - If is_new=False: strategy_<name>.json exists and config["magic_number"] matches stored value
    """

    name         = config["name"]
    display_name = config["display_name"]
    description  = config.get("description", "")
    timeframe    = config["timeframe"]
    magic_number = config["magic_number"]
    indicators   = config["indicators"]
    buy_cond     = config["buy_condition"]
    sell_cond    = config["sell_condition"]

    # --- Derived metadata ---
    custom_indicators   = [ind for ind in indicators if not ind["pre_computed"]]
    needs_prepare       = len(custom_indicators) > 0
    needs_volume        = any(ind["id"] in ("VWAP", "VOLUME_RATIO") for ind in custom_indicators)
    needs_high_low      = any(ind["id"] in ("DONCHIAN", "ATR", "VWAP") for ind in custom_indicators)
    needs_close         = any(ind["id"] in ("EMA", "RSI", "BB", "ATR", "VWAP", "VOLUME_RATIO", "SMA")
                              for ind in custom_indicators)

    condition_columns = collect_leaf_columns(buy_cond) | collect_leaf_columns(sell_cond)
    # collect_leaf_columns: recursively walks condition tree, returns set of all "left" and
    # string-typed "right" values (column references, not scalars)

    # --- Assemble sections ---
    sections = []
    sections.append( emit_docstring(display_name, description, timeframe) )
    sections.append( "import pandas as pd" )
    sections.append( emit_module_constants(timeframe, magic_number, indicators) )
    sections.append( emit_data_window_fields(indicators) )
    sections.append( emit_helper_functions(indicators) )

    if needs_prepare:
        sections.append( emit_prepare_dataframe(indicators, needs_close, needs_high_low, needs_volume) )

    sections.append( emit_compute_signals(buy_cond, sell_cond, condition_columns) )
    sections.append( emit_get_last_signal_payload(display_name) )
    sections.append( emit_get_last_signal(buy_cond, sell_cond) )

    # --- Assemble and validate ---
    py_content = "\n\n".join(sections) + "\n"
    ast.parse(py_content)
    # If ast.parse raises SyntaxError: do NOT write any files; propagate error to caller

    # --- Atomic write ---
    py_path   = strategies_dir / f"strategy_{name}.py"
    json_path = strategies_dir / f"strategy_{name}.json"

    write_atomic(py_path,   py_content)
    write_atomic(json_path, json.dumps(config, indent=2, ensure_ascii=False))

    return py_path
```

**`write_atomic(path, content)`**:
```
function write_atomic(path: Path, content: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    write tmp with content (UTF-8)
    rename tmp → path   # atomic on same filesystem
    # On failure: remove tmp if it exists; re-raise exception
```

---

### 4.2 `emit_docstring`

```
function emit_docstring(display_name, description, timeframe) -> str:
    desc_line = f"\n{description}" if description else ""
    return f'"""\n{display_name} — {timeframe}{desc_line}\nGenerated by Strategy Builder. Edit via the Builder UI, not this file.\n"""'
```

---

### 4.3 `emit_module_constants`

Emits `TIMEFRAME`, `MAGIC_NUMBER`, and one named constant per configurable indicator parameter.

```
function emit_module_constants(timeframe, magic_number, indicators) -> str:
    lines = []
    lines.append(f'TIMEFRAME = "{timeframe}"')
    lines.append(f'MAGIC_NUMBER = {magic_number}')

    for ind in indicators:
        if ind["pre_computed"]:
            continue   # no constants for locked global indicators

        id = ind["id"]
        p  = ind["params"]

        if id == "EMA":
            period = int(p["period"])
            lines.append(f"EMA_{period}_PERIOD = {period}")

        elif id == "RSI":
            period = int(p["period"])
            lines.append(f"RSI_{period}_PERIOD = {period}")

        elif id == "BB":
            period = int(p["period"])
            mult   = p["multiplier"]
            lines.append(f"BB_{period}_PERIOD = {period}")
            lines.append(f"BB_{period}_MULT = {mult}")

        elif id == "DONCHIAN":
            period = int(p["period"])
            lines.append(f"DONCHIAN_{period}_PERIOD = {period}")

        elif id == "ATR":
            period = int(p["period"])
            lines.append(f"ATR_{period}_PERIOD = {period}")

        elif id == "VOLUME_RATIO":
            lookback = int(p["lookback"])
            lines.append(f"VOLUME_RATIO_{lookback}_LOOKBACK = {lookback}")

        elif id == "SMA":
            period = int(p["period"])
            lines.append(f"SMA_{period}_PERIOD = {period}")

        # VWAP: no parameters → no constants

    return "\n".join(lines)
```

---

### 4.4 `emit_data_window_fields`

Maps each indicator instance to its DATA_WINDOW_FIELDS entries. Signal entries are always appended last.

```
function emit_data_window_fields(indicators) -> str:
    entries = []

    for ind in indicators:
        id = ind["id"]
        p  = ind["params"]

        if id == "EMA":
            period = int(p["period"])
            entries.append(f'{{"key": "ema_{period}", "label": "EMA ({period})", "format": "price", "section": "Trend"}}')

        elif id == "RSI":
            period = int(p["period"])
            entries.append(f'{{"key": "rsi_{period}", "label": "RSI ({period})", "format": "number", "section": "Momentum"}}')

        elif id == "BB":
            period = int(p["period"])
            entries.append(f'{{"key": "bb_basis_{period}", "label": "BB Basis ({period})", "format": "price", "section": "Bollinger"}}')
            entries.append(f'{{"key": "bb_upper_{period}", "label": "BB Upper ({period})", "format": "price", "section": "Bollinger"}}')
            entries.append(f'{{"key": "bb_lower_{period}", "label": "BB Lower ({period})", "format": "price", "section": "Bollinger"}}')
            entries.append(f'{{"key": "bb_width_pct_{period}", "label": "BB Width % ({period})", "format": "percent", "section": "Bollinger"}}')

        elif id == "DONCHIAN":
            period = int(p["period"])
            entries.append(f'{{"key": "donchian_high_{period}", "label": "Donchian High ({period})", "format": "price", "section": "Donchian"}}')
            entries.append(f'{{"key": "donchian_low_{period}", "label": "Donchian Low ({period})", "format": "price", "section": "Donchian"}}')
            entries.append(f'{{"key": "donchian_mid_{period}", "label": "Donchian Mid ({period})", "format": "price", "section": "Donchian"}}')

        elif id == "ATR":
            period = int(p["period"])
            entries.append(f'{{"key": "atr_{period}", "label": "ATR ({period})", "format": "price", "section": "Volatility"}}')
            entries.append(f'{{"key": "atr_pct_{period}", "label": "ATR % ({period})", "format": "percent", "section": "Volatility"}}')

        elif id == "VWAP":
            entries.append('{"key": "vwap", "label": "VWAP", "format": "price", "section": "VWAP"}')

        elif id == "VOLUME_RATIO":
            lookback = int(p["lookback"])
            entries.append(f'{{"key": "volume_ratio_{lookback}", "label": "Volume Ratio ({lookback})", "format": "number", "section": "Volume"}}')

        elif id == "SMA":
            period = int(p["period"])
            entries.append(f'{{"key": "sma_{period}", "label": "SMA ({period})", "format": "price", "section": "Trend"}}')

        elif id == "HMA":
            entries.append('{"key": "hma", "label": "HMA (55)", "format": "price", "section": "Trend"}')

        elif id == "SUPERTREND":
            entries.append('{"key": "supertrend_dir", "label": "Supertrend Dir", "format": "number", "section": "Supertrend"}')
            entries.append('{"key": "supertrend", "label": "Supertrend", "format": "price", "section": "Supertrend"}')

        elif id == "TCI":
            entries.append('{"key": "tci", "label": "TCI", "format": "number", "section": "TCI"}')
            entries.append('{"key": "tci_signal", "label": "TCI Signal", "format": "number", "section": "TCI"}')
            entries.append('{"key": "tci_hist", "label": "TCI Hist", "format": "number", "section": "TCI"}')

    # Always-last: signal columns
    entries.append('{"key": "up_sig", "label": "Buy Signal", "format": "int", "section": "Signals", "shift": 1}')
    entries.append('{"key": "dn_sig", "label": "Sell Signal", "format": "int", "section": "Signals", "shift": 1}')

    inner = ",\n    ".join(entries)
    return f"DATA_WINDOW_FIELDS = [\n    {inner},\n]"
```

---

### 4.5 `emit_helper_functions`

Helper functions are conditionally emitted based on the selected indicators. Each helper body is verbatim — the coding agent copies the exact implementation from the reference strategies. The pseudocode here specifies which helper is emitted under which condition.

```
function emit_helper_functions(indicators) -> str:
    ids = {ind["id"] for ind in indicators}
    custom_ids = {ind["id"] for ind in indicators if not ind["pre_computed"]}

    blocks = []

    # _numeric: always emitted (used by compute_signals regardless of indicators)
    blocks.append( TEMPLATE_NUMERIC )

    # _volume_series: emitted if VWAP or VOLUME_RATIO is selected
    if "VWAP" in custom_ids or "VOLUME_RATIO" in custom_ids:
        blocks.append( TEMPLATE_VOLUME_SERIES )

    # _rsi: emitted if RSI is selected
    if "RSI" in custom_ids:
        blocks.append( TEMPLATE_RSI )

    # _atr: emitted if ATR is selected
    if "ATR" in custom_ids:
        blocks.append( TEMPLATE_ATR )

    # _intraday_vwap: emitted if VWAP is selected
    if "VWAP" in custom_ids:
        blocks.append( TEMPLATE_INTRADAY_VWAP )

    return "\n\n".join(blocks)
```

**Helper function template bodies** (verbatim — coding agent uses exact source from reference strategies):

```
TEMPLATE_NUMERIC:
def _numeric(df: pd.DataFrame, key: str) -> pd.Series:
    return pd.to_numeric(df.get(key), errors="coerce")

TEMPLATE_VOLUME_SERIES:
def _volume_series(df: pd.DataFrame) -> pd.Series:
    if "tick_volume" in df.columns:
        return pd.to_numeric(df.get("tick_volume"), errors="coerce")
    if "volume" in df.columns:
        return pd.to_numeric(df.get("volume"), errors="coerce")
    return pd.Series(1.0, index=df.index, dtype="float64")

TEMPLATE_RSI:   # verbatim from strategy_ema_rsi_trend._rsi
def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0.0)
    loss     = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))

TEMPLATE_ATR:   # verbatim from strategy_donchian_breakout._atr
def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low,
         (high - prev_close).abs(),
         (low  - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()

TEMPLATE_INTRADAY_VWAP:   # verbatim from strategy_ema_rsi_trend._intraday_vwap
def _intraday_vwap(df: pd.DataFrame,
                   high: pd.Series, low: pd.Series,
                   close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price  = (high + low + close) / 3.0
    weighted_price = typical_price * volume
    if "time" in df.columns:
        session_key = pd.to_datetime(df["time"], utc=True, errors="coerce").dt.floor("D")
    else:
        session_key = pd.Series(0, index=df.index)
    cum_wp  = weighted_price.groupby(session_key).cumsum()
    cum_vol = volume.groupby(session_key).cumsum().replace(0.0, float("nan"))
    return cum_wp / cum_vol
```

---

### 4.6 `emit_prepare_dataframe`

Only called when `needs_prepare = True`. Emits one computation block per non-pre-computed indicator.

```
function emit_prepare_dataframe(indicators, needs_close, needs_high_low, needs_volume) -> str:
    custom_indicators = [ind for ind in indicators if not ind["pre_computed"]]

    # --- Determine required raw inputs for the guard check ---
    required = {"close"} if needs_close else set()
    if needs_high_low: required |= {"high", "low"}
    # volume is obtained via _volume_series which has its own fallback — not in required

    required_repr = "{" + ", ".join(repr(c) for c in sorted(required)) + "}"

    # --- Build function body lines ---
    body = []
    body.append("    out = df.copy()")
    body.append(f"    required = {required_repr}")
    body.append("    if not required.issubset(out.columns):")
    body.append("        return out")

    # Raw column extractions
    if needs_close:
        body.append('    close = _numeric(out, "close")')
    if needs_high_low:
        body.append('    high  = _numeric(out, "high")')
        body.append('    low   = _numeric(out, "low")')
    if needs_volume:
        body.append("    volume = _volume_series(out)")

    # Indicator computation blocks (in order)
    for ind in custom_indicators:
        body.extend( emit_indicator_computation_block(ind) )

    # DataFrame column assignments (in same order)
    for ind in custom_indicators:
        for col in ind["columns"]:
            local_var = col   # local variable name == column name (e.g. "ema_9", "bb_basis_20")
            body.append(f'    out["{col}"] = {local_var}')

    body.append("    return out")

    return "def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:\n" + "\n".join(body)
```

**`emit_indicator_computation_block(ind) -> list[str]`**:

```
function emit_indicator_computation_block(ind) -> list[str]:
    id = ind["id"]
    p  = ind["params"]

    if id == "EMA":
        period = int(p["period"])
        return [f"    ema_{period} = close.ewm(span={period}, adjust=False).mean()"]

    elif id == "RSI":
        period = int(p["period"])
        return [f"    rsi_{period} = _rsi(close, {period})"]

    elif id == "BB":
        period = int(p["period"])
        mult   = p["multiplier"]
        return [
            f"    bb_basis_{period}     = close.rolling({period}, min_periods={period}).mean()",
            f"    bb_std_{period}       = close.rolling({period}, min_periods={period}).std(ddof=0)",
            f"    bb_upper_{period}     = bb_basis_{period} + (bb_std_{period} * {mult})",
            f"    bb_lower_{period}     = bb_basis_{period} - (bb_std_{period} * {mult})",
            f"    bb_width_pct_{period} = (bb_upper_{period} - bb_lower_{period}) / bb_basis_{period}.replace(0.0, float('nan'))",
        ]
        # Note: bb_std_<period> is a local intermediate — NOT written to the DataFrame

    elif id == "DONCHIAN":
        period = int(p["period"])
        return [
            f"    donchian_high_{period} = high.rolling({period}, min_periods={period}).max().shift(1)",
            f"    donchian_low_{period}  = low.rolling({period}, min_periods={period}).min().shift(1)",
            f"    donchian_mid_{period}  = (donchian_high_{period} + donchian_low_{period}) / 2.0",
        ]

    elif id == "ATR":
        period = int(p["period"])
        return [
            f"    atr_{period}     = _atr(high, low, close, {period})",
            f"    atr_pct_{period} = atr_{period} / close.replace(0.0, float('nan'))",
        ]

    elif id == "VWAP":
        return ["    vwap = _intraday_vwap(out, high, low, close, volume)"]

    elif id == "VOLUME_RATIO":
        lookback = int(p["lookback"])
        return [
            f"    vol_ma_{lookback}          = volume.rolling({lookback}, min_periods=5).mean()",
            f"    volume_ratio_{lookback}    = volume / vol_ma_{lookback}.replace(0.0, float('nan'))",
        ]
        # Note: vol_ma_<lookback> is a local intermediate — NOT written to the DataFrame

    elif id == "SMA":
        period = int(p["period"])
        return [f"    sma_{period} = close.rolling({period}, min_periods={period}).mean()"]

    else:
        raise ValueError(f"emit_indicator_computation_block: unknown id '{id}'")
```

**Note on intermediate variables**: `bb_std_<period>` and `vol_ma_<lookback>` are local intermediate variables used in the computation. They are NOT in `ind["columns"]` and are NOT written to `out`. The DataFrame assignment loop in `emit_prepare_dataframe` only iterates over `ind["columns"]`, so they are automatically excluded.

---

### 4.7 `emit_vectorized_condition` (new in TASK-014c)

This is a second emitter, separate from TASK-014b's `emit_condition`. It produces a pandas boolean Series expression for use in `compute_signals`. The structure mirrors `emit_condition` exactly but replaces `df.iloc[-2]["col"]` with `out["col"]` (a Series) and `and`/`or` with `&`/`|`.

```
function emit_vectorized_condition(node: dict) -> str:
    """
    Preconditions: same as emit_condition (tree is pre-validated).
    Uses the local variable name "out" matching compute_signals's "out = df.copy()".
    Every leaf node is parenthesized to prevent pandas operator precedence issues
    (& and | have lower precedence than comparison operators in Python, but
     explicit parentheses make it unambiguous regardless).
    """

    if node["type"] == "condition":
        left_expr = f'out["{node["left"]}"]'

        right = node["right"]
        if isinstance(right, (int, float)):
            if isinstance(right, float) and right == int(right):
                right_expr = str(int(right))
            else:
                right_expr = repr(right)
        else:
            right_expr = f'out["{right}"]'

        return f"({left_expr} {node['op']} {right_expr})"

    elif node["type"] in ("AND", "OR"):
        connector = " & " if node["type"] == "AND" else " | "
        child_exprs = [emit_vectorized_condition(child) for child in node["children"]]
        joined = connector.join(child_exprs)
        return f"({joined})"

    else:
        raise ValueError(f"emit_vectorized_condition: unknown node type '{node['type']}'")
```

**Example**: The same condition tree from TASK-014b — `(A AND B) OR (C AND D)` — produces:
```python
((out["rsi_14"] < 30) & (out["close"] > out["ema_9"])) | ((out["close"] > out["bb_upper_20"]) & (out["volume_ratio_30"] > 1.5))
```

This is a valid pandas expression returning a boolean Series of length `len(out)`.

---

### 4.8 `emit_compute_signals`

```
function emit_compute_signals(buy_condition, sell_condition, condition_columns) -> str:
    buy_vec_expr  = emit_vectorized_condition(buy_condition)
    sell_vec_expr = emit_vectorized_condition(sell_condition)

    needed_repr = "{" + ", ".join(repr(c) for c in sorted(condition_columns)) + "}"

    return f"""def compute_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:
    out = df.copy()
    needed = {needed_repr}
    if not needed.issubset(out.columns):
        out["long_setup"]  = 0
        out["short_setup"] = 0
        out["up_sig"]      = 0
        out["dn_sig"]      = 0
        return out

    if enable_signals:
        buy_signal  = {buy_vec_expr}
        sell_signal = {sell_vec_expr}
    else:
        buy_signal  = pd.Series(False, index=out.index)
        sell_signal = pd.Series(False, index=out.index)

    out["long_setup"]  = buy_signal.astype(int)
    out["short_setup"] = sell_signal.astype(int)
    out["up_sig"]      = buy_signal.astype(int)
    out["dn_sig"]      = sell_signal.astype(int)
    return out"""
```

**Note on `long_setup` == `up_sig`**: For Builder-generated strategies, `long_setup` is identical to `up_sig` (and `short_setup` identical to `dn_sig`). There is no multi-step setup/confirmation pattern. This is simpler than the hand-written reference strategies and is the correct choice — the Builder doesn't expose a two-step pattern, and forcing one would be unsound without explicit user control.

---

### 4.9 `emit_get_last_signal_payload`

```
function emit_get_last_signal_payload(display_name) -> str:
    return f"""def get_last_signal_payload(df: pd.DataFrame, verbose: bool = False) -> dict:
    signal = get_last_signal(df, verbose=verbose)
    reasons = {{
        "buy":  "{display_name}: buy condition met",
        "sell": "{display_name}: sell condition met",
        "none": "{display_name}: no signal",
    }}
    return {{"signal": signal, "reason": reasons[signal]}}"""
```

---

### 4.10 `emit_get_last_signal`

Uses the scalar emitter from TASK-014b (`emit_condition`) to embed the condition tree directly as an `if` expression. This makes `get_last_signal` self-contained — it evaluates the condition tree on `df.iloc[-2]` without reading `up_sig`.

```
function emit_get_last_signal(buy_condition, sell_condition) -> str:
    buy_expr  = emit_condition(buy_condition)   # from TASK-014b — produces df.iloc[-2]["col"] expressions
    sell_expr = emit_condition(sell_condition)

    return f"""def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    if df is None or len(df) < 3:
        return "none"
    if {buy_expr}:
        return "buy"
    elif {sell_expr}:
        return "sell"
    return "none\""""
```

**Design rationale**: `get_last_signal` evaluates conditions directly rather than reading from `up_sig` (unlike the reference hand-written strategies). This ensures:
1. `get_last_signal` works correctly when called from `main.py`'s trading loop even if `compute_signals` has not been called
2. `compute_signals` is purely for the GUI chart markers and has no effect on trading decisions
3. The two functions are independent — both encode the same logic but serve different callers

The cost is that the condition logic is evaluated twice per trading cycle (once vectorized in `compute_signals`, once scalar in `get_last_signal`). At n=500 and k=3 strategies, this is negligible.

---

## 5. Persistence and Edit (Round-Trip) Spec

### 5.1 Filename convention

| File | Path |
|------|------|
| Generated strategy | `strategies/strategy_<name>.py` |
| Companion config | `strategies/strategy_<name>.json` |

Both files share the same `<name>` — the `name` field from the strategy config. They always coexist: the generator writes both atomically or writes neither.

### 5.2 How the GUI detects editable strategies

On strategy list load, the GUI iterates `strategies/strategy_*.py` files. For each file `strategy_<name>.py`, it checks for `strategy_<name>.json`:
- **`.json` exists** → strategy is Builder-generated; GUI shows "Edit" button
- **`.json` absent** → strategy is hand-crafted by a technical user; GUI shows the strategy in the list but without an "Edit" button (or with "View only" label)

This detection is file-existence-based only — the GUI does not parse the `.py` file to determine origin.

### 5.3 Create flow

```
function handle_save_new(raw_config_from_gui: dict):
    # 1. Sanitize name (see EC-S3)
    raw_config_from_gui["name"] = sanitize_name(raw_config_from_gui["display_name"])

    # 2. Check for collision
    name = raw_config_from_gui["name"]
    py_path   = strategies_dir / f"strategy_{name}.py"
    json_path = strategies_dir / f"strategy_{name}.json"

    if py_path.exists() and not json_path.exists():
        raise NameCollisionError("A hand-crafted strategy with this name already exists.")
    if py_path.exists() and json_path.exists():
        raise NameCollisionError("A Builder strategy with this name already exists. Use Edit.")

    # 3. Assign magic_number
    raw_config_from_gui["magic_number"] = generate_magic_number()
    # generate_magic_number: returns random.randint(10000, 99999)
    # Stable per strategy because it is stored in the .json and reused on all edits

    # 4. Set schema_version
    raw_config_from_gui["schema_version"] = 1

    # 5. Validate
    validate_strategy_config(raw_config_from_gui, is_new=True)

    # 6. Generate
    generate_strategy_file(raw_config_from_gui, strategies_dir, is_new=True)
```

### 5.4 Edit flow

```
function handle_save_edit(raw_config_from_gui: dict, original_name: str):
    # raw_config_from_gui contains the form data after user edits
    # original_name is the strategy name that was opened for editing (may differ if user renamed)

    # 1. Load stored .json to recover magic_number
    stored_json_path = strategies_dir / f"strategy_{original_name}.json"
    stored_config    = json.loads(stored_json_path.read_text())
    preserved_magic  = stored_config["magic_number"]

    # 2. Handle rename (user changed display_name → new canonical name)
    new_name = sanitize_name(raw_config_from_gui["display_name"])
    if new_name != original_name:
        # Check new name doesn't collide
        new_py   = strategies_dir / f"strategy_{new_name}.py"
        new_json = strategies_dir / f"strategy_{new_name}.json"
        if new_py.exists():
            raise NameCollisionError(f"Name '{new_name}' is already taken.")
        # Old files will be deleted after successful write of new files

    raw_config_from_gui["name"]          = new_name
    raw_config_from_gui["magic_number"]  = preserved_magic   # always preserved
    raw_config_from_gui["schema_version"] = 1

    # 3. Validate
    validate_strategy_config(raw_config_from_gui, is_new=False)

    # 4. Generate new files
    generate_strategy_file(raw_config_from_gui, strategies_dir, is_new=False)

    # 5. Remove old files only if rename occurred and new files were written successfully
    if new_name != original_name:
        (strategies_dir / f"strategy_{original_name}.py").unlink()
        (strategies_dir / f"strategy_{original_name}.json").unlink()
```

### 5.5 Overwrite contract summary

| Action | `.py` | `.json` | Old files |
|--------|-------|---------|-----------|
| Create (no rename) | Written (new) | Written (new) | N/A |
| Edit (no rename) | Overwritten | Overwritten | N/A |
| Edit (with rename) | Written as new name | Written as new name | Old `.py` + `.json` deleted after successful write |
| Generator error | Not written | Not written | Unchanged |
| `ast.parse` failure | Not written | Not written | Unchanged |
| Atomic rename failure | `.tmp` cleaned up | `.tmp` cleaned up | Unchanged |

**Atomicity guarantee**: The two `.tmp` → rename operations are sequential, not simultaneously atomic at the OS level. The write sequence is: write `strategy_<name>.py.tmp`, write `strategy_<name>.json.tmp`, rename `.py.tmp` → `.py`, rename `.json.tmp` → `.json`. If the second rename fails after the first succeeds, the `.py` is written but the `.json` is not — the strategy file exists but will be treated as hand-crafted (no Edit button). This is an acceptable inconsistency for v1. A future version may use a two-phase commit approach. The caller should detect this state and show a warning.

---

## 6. Validator Pseudocode (`validate_strategy_config`)

The validator is called before the generator. All edge cases in this section and in TASK-014b are enforced here.

```
function validate_strategy_config(config: dict, is_new: bool) -> None:
    # Raises ValidationError with a human-readable message on any failure.

    # --- Schema-level checks ---
    enforce_json_schema(config, STRATEGY_CONFIG_SCHEMA)   # against the schema in Section 2.1

    # --- Name checks ---
    name = config["name"]
    if not re.match(r'^[a-z][a-z0-9_]*$', name):
        raise ValidationError(f"Invalid strategy name '{name}'. Use lowercase letters, digits, underscores only.")

    py_path   = strategies_dir / f"strategy_{name}.py"
    json_path = strategies_dir / f"strategy_{name}.json"

    if is_new:
        if py_path.exists() and not json_path.exists():
            raise ValidationError("A hand-crafted strategy with this name already exists.")
        if py_path.exists() and json_path.exists():
            raise ValidationError("A Builder strategy with this name already exists. Use Edit to modify it.")

    # --- Indicator deduplication (EC-S6) ---
    seen = {}
    deduplicated = []
    for ind in config["indicators"]:
        key = (ind["id"], json.dumps(ind["params"], sort_keys=True))
        if key not in seen:
            seen[key] = True
            deduplicated.append(ind)
        # Silently drop duplicate (identical id + params)
    config["indicators"] = deduplicated

    # --- Compute available column set ---
    available_columns = ALWAYS_AVAILABLE_COLUMNS.copy()
    # ALWAYS_AVAILABLE_COLUMNS = {"open", "high", "low", "close", "OHLC4", "HLC3", "HL2",
    #                              "tick_volume", "average", "atr", "upper", "lower",
    #                              "hma", "supertrend", "supertrend_dir", "supertrend_up",
    #                              "supertrend_down", "tci", "tci_signal", "tci_hist"}
    for ind in config["indicators"]:
        available_columns.update(ind["columns"])

    # --- Condition tree structural validation ---
    validate_condition_node(config["buy_condition"],  available_columns, path="buy_condition")
    validate_condition_node(config["sell_condition"], available_columns, path="sell_condition")

    # --- Identical buy/sell warning (EC-3 from TASK-014b) ---
    if (json.dumps(config["buy_condition"],  sort_keys=True) ==
        json.dumps(config["sell_condition"], sort_keys=True)):
        emit_warning("Buy and sell conditions are identical — strategy will always trade buy on conflict.")
        # Not a blocking error; user may save anyway

    # --- VWAP + D1 warning (TASK-014a) ---
    has_vwap = any(ind["id"] == "VWAP" for ind in config["indicators"])
    if has_vwap and config["timeframe"] == "D1":
        emit_warning("VWAP is not meaningful on D1 timeframe.")

    # --- Param type coercion (EC-S7) ---
    for ind in config["indicators"]:
        p = ind["params"]
        if "period"   in p: p["period"]   = int(p["period"])
        if "lookback" in p: p["lookback"] = int(p["lookback"])
        # multiplier stays float

function validate_condition_node(node: dict, available_columns: set, path: str) -> None:
    if node["type"] == "condition":
        if node["left"] not in available_columns:
            raise ValidationError(f"{path}: column '{node['left']}' not available. Add the corresponding indicator.")
        right = node["right"]
        if isinstance(right, str) and right not in available_columns:
            raise ValidationError(f"{path}: column '{right}' (right operand) not available. Add the corresponding indicator.")
        if node["op"] not in ("<", ">", "<=", ">=", "==", "!="):
            raise ValidationError(f"{path}: invalid operator '{node['op']}'.")

    elif node["type"] in ("AND", "OR"):
        if len(node["children"]) < 2:
            raise ValidationError(f"{path}: group must contain at least 2 conditions (found {len(node['children'])}).")
        for i, child in enumerate(node["children"]):
            validate_condition_node(child, available_columns, f"{path}.children[{i}]")

    else:
        raise ValidationError(f"{path}: unknown node type '{node['type']}'.")
```

---

## 7. Edge Cases

### Carried over from TASK-014b (EC-1 through EC-8)

All eight edge cases from TASK-014b apply unchanged. The validator is the gatekeeper; the generator assumes pre-validated input. Key points:
- EC-1 (empty children): blocked by validator
- EC-2 (single-child group): blocked by validator (N ≥ 2 enforced)
- EC-3 (identical buy/sell): warning, not blocking
- EC-4 (max nesting depth): GUI enforces ≤ 5 levels
- EC-5 (scalar int/float formatting): handled in both emitters
- EC-6 (op injection): validator whitelist + final `ast.parse`
- EC-7 (column names with special chars): not possible given catalogue
- EC-8 (string that looks like a number): validator catches

### New schema-level edge cases (EC-S1 through EC-S9)

**EC-S1: Name collision with hand-crafted strategy**
User tries to create a strategy with a name that already exists as a manual `.py` (no `.json`).
Prescribed: validator blocks with clear error. Builder never silently overwrites hand-crafted files.

**EC-S2: Name collision with existing Builder strategy on create**
User creates new strategy with a name that already has both `.py` and `.json`.
Prescribed: validator blocks with "already exists — use Edit".

**EC-S3: Display name sanitization to canonical name**
User display name may contain spaces, hyphens, accented characters, capitals.
Prescribed:
```
sanitize_name(display_name):
    s = display_name.lower()
    s = re.sub(r'[^a-z0-9_]', '_', s)   # replace all non-alphanumeric with underscore
    s = re.sub(r'_+', '_', s)            # collapse multiple underscores
    s = s.strip('_')                     # trim leading/trailing underscores
    if not s or s[0].isdigit():
        s = 'strategy_' + s             # ensure starts with letter
    # Collision suffix: if s already taken, append _2, _3, ...
    return s
```

**EC-S4: Empty indicators list (all pre-computed or none selected)**
Valid state. `needs_prepare = False`, `prepare_dataframe` is not emitted. Generator handles gracefully.

**EC-S5: Condition tree references column not produced by selected indicators**
Validator catches at save time via `available_columns` check.

**EC-S6: Duplicate indicator instances**
Two identical `{id, params}` objects in the `indicators` list.
Prescribed: validator deduplicates silently (first occurrence kept).

**EC-S7: Floating-point period values from GUI sliders**
`params["period"] = 14.000000001` due to slider precision.
Prescribed: validator coerces to `int`. Integer periods only; `multiplier` stays float.

**EC-S8: Atomic write failure**
`.tmp` files cleaned up on any exception. Original files not modified.

**EC-S9: Strategy reload after generation**
The generator only writes files — it does not reload modules.
The caller (in `gui_charts.py`) is responsible for triggering `_reload_strategy_list()` after a successful `generate_strategy_file()` call. For the edit flow, `importlib.reload()` must be used since the module may already be loaded. This is a TASK-016/TASK-017 implementation concern, not a generator spec concern.

---

## 8. Complete Example of Generated `.py`

For the `ema_rsi_cross` config from Section 2.3 (EMA(9), EMA(21), RSI(14), buy: `ema_9 > ema_21 AND rsi_14 > 50`):

```python
"""
EMA Cross + RSI Filter — H1
Buy when fast EMA crosses above slow EMA and RSI is in momentum zone.
Generated by Strategy Builder. Edit via the Builder UI, not this file.
"""

import pandas as pd

TIMEFRAME = "H1"
MAGIC_NUMBER = 47231
EMA_9_PERIOD = 9
EMA_21_PERIOD = 21
RSI_14_PERIOD = 14

DATA_WINDOW_FIELDS = [
    {"key": "ema_9",    "label": "EMA (9)",    "format": "price",  "section": "Trend"},
    {"key": "ema_21",   "label": "EMA (21)",   "format": "price",  "section": "Trend"},
    {"key": "rsi_14",   "label": "RSI (14)",   "format": "number", "section": "Momentum"},
    {"key": "up_sig",   "label": "Buy Signal", "format": "int",    "section": "Signals", "shift": 1},
    {"key": "dn_sig",   "label": "Sell Signal","format": "int",    "section": "Signals", "shift": 1},
]


def _numeric(df: pd.DataFrame, key: str) -> pd.Series:
    return pd.to_numeric(df.get(key), errors="coerce")


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0.0)
    loss     = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    required = {"close"}
    if not required.issubset(out.columns):
        return out
    close    = _numeric(out, "close")
    ema_9    = close.ewm(span=9,  adjust=False).mean()
    ema_21   = close.ewm(span=21, adjust=False).mean()
    rsi_14   = _rsi(close, 14)
    out["ema_9"]  = ema_9
    out["ema_21"] = ema_21
    out["rsi_14"] = rsi_14
    return out


def compute_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:
    out = df.copy()
    needed = {"ema_21", "ema_9", "rsi_14"}
    if not needed.issubset(out.columns):
        out["long_setup"]  = 0
        out["short_setup"] = 0
        out["up_sig"]      = 0
        out["dn_sig"]      = 0
        return out

    if enable_signals:
        buy_signal  = ((out["ema_9"] > out["ema_21"]) & (out["rsi_14"] > 50))
        sell_signal = ((out["ema_9"] < out["ema_21"]) & (out["rsi_14"] < 50))
    else:
        buy_signal  = pd.Series(False, index=out.index)
        sell_signal = pd.Series(False, index=out.index)

    out["long_setup"]  = buy_signal.astype(int)
    out["short_setup"] = sell_signal.astype(int)
    out["up_sig"]      = buy_signal.astype(int)
    out["dn_sig"]      = sell_signal.astype(int)
    return out


def get_last_signal_payload(df: pd.DataFrame, verbose: bool = False) -> dict:
    signal = get_last_signal(df, verbose=verbose)
    reasons = {
        "buy":  "EMA Cross + RSI Filter: buy condition met",
        "sell": "EMA Cross + RSI Filter: sell condition met",
        "none": "EMA Cross + RSI Filter: no signal",
    }
    return {"signal": signal, "reason": reasons[signal]}


def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    if df is None or len(df) < 3:
        return "none"
    if (df.iloc[-2]["ema_9"] > df.iloc[-2]["ema_21"] and df.iloc[-2]["rsi_14"] > 50):
        return "buy"
    elif (df.iloc[-2]["ema_9"] < df.iloc[-2]["ema_21"] and df.iloc[-2]["rsi_14"] < 50):
        return "sell"
    return "none"
```

**Verification checklist for this example**:
- ✅ No imports from `config`, `trading`, or `gui_charts`
- ✅ `TIMEFRAME` constant present
- ✅ `MAGIC_NUMBER` constant present
- ✅ `DATA_WINDOW_FIELDS` present
- ✅ `prepare_dataframe` computes all columns referenced in condition trees
- ✅ `compute_signals` uses vectorized expressions matching the condition trees
- ✅ `get_last_signal` uses `df.iloc[-2]` direct evaluation (scalar emitter output)
- ✅ Returns `"buy"`, `"sell"`, or `"none"` — no other values
- ✅ Would pass `ast.parse`

---

## 9. Final Sub-Team Assessment

**Question**: Is the overall Strategy Builder scope large enough to warrant a dedicated sub-team brief to Jarvis before TASK-015 is assigned?

**Assessment**: **No dedicated sub-team needed. Proceed directly to TASK-015 (Grace).**

Implementation breakdown:
| Component | Module | Estimated lines | Assignee |
|-----------|--------|-----------------|---------|
| `emit_condition` (scalar) | `strategies/builder.py` | ~40 | TASK-017 |
| `emit_vectorized_condition` | `strategies/builder.py` | ~25 | TASK-017 |
| `validate_strategy_config` + `validate_condition_node` | `strategies/builder.py` | ~60 | TASK-017 |
| Indicator emitters (`emit_indicator_computation_block`, etc.) | `strategies/builder.py` | ~80 | TASK-017 |
| Section assembly (`emit_prepare_dataframe`, `emit_compute_signals`, etc.) | `strategies/builder.py` | ~120 | TASK-017 |
| `generate_strategy_file` + `write_atomic` + create/edit flows | `strategies/builder.py` | ~70 | TASK-017 |
| **Total** | | **~395 lines** | |

All functions are mechanical translations of the pseudocode in this spec (and TASK-014b). No architectural decisions remain for the implementer. TASK-017 is a single well-scoped implementation task.

TASK-015 (Grace) may proceed without waiting — this spec is the complete gate. Grace has all data model information needed to design the GUI panel and event flows.

---

## 10. Deliverable Summary for Downstream Tasks

### For TASK-015 (Grace — GUI spec):
- The complete `StrategyConfig` JSON schema (Section 2.1) is the payload shape for the GUI "Save" event
- Indicator config structure (Section 2.2) defines what indicator selection state the GUI must collect and serialize
- `ConditionNode` schema (Section 2.1 `$defs`) defines the condition tree the GUI combinator must produce
- The `name` field is derived from `display_name` at save time via `sanitize_name()` — the GUI should show the auto-generated name to the user for confirmation before saving
- Edit flow requires loading `strategy_<name>.json` on "Edit" button press and pre-populating the form from all config fields
- **La GUI es responsable de construir el array `columns` de cada indicador usando la convención de nombres de la Sección 2.2 (e.g. `ema_<period>`, `rsi_<period>`) y de incluirlo en el payload del evento Save.** El generador usa `ind["columns"]` directamente y nunca re-deriva los nombres a partir de `id + params`.

### For TASK-017 (generator implementation):
- This document is the complete implementation spec. The coding agent translates pseudocode to Python — no design decisions needed.
- Generator entry point: `generate_strategy_file(config: dict, strategies_dir: Path, is_new: bool) -> Path`
- All pseudocode functions map directly to Python functions in `strategies/builder.py`
- `emit_condition` from TASK-014b is also in `strategies/builder.py` (same module)
- Final `ast.parse` check is mandatory before any file write
- Module must not be imported by generated strategies (isolation rule)
