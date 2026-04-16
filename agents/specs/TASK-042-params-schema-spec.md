# Pre-Implementation: PARAMS Schema, Merge Logic & Injection in main.py

**By**: Daniel
**Date**: 2026-04-14
**Task**: TASK-042
**Status**: ready

---

## Formal Problem Statement

**Input** (three separate sub-problems handled below):

1. `_load_strategy_params(module, strategy_key, strategies_dir) -> dict`
   - `module`: a loaded Python module object; may or may not expose a `PARAMS` attribute
   - `strategy_key`: `str`, slugified key identifying the strategy (e.g. `"primera_estrategia"`)
   - `strategies_dir`: `str` absolute path to the strategies folder

2. `_load_strategy_module()` extension
   - Current return: a module object
   - Required extension: the entry dict built in `load_active_strategies()` must also store `params_schema` and `params_values`

3. `_analyze_strategy()` extension
   - Current: calls `runtime_get_strategy_signal_payload(strategy_df, entry["module"], verbose=False)`
   - Required: if `get_last_signal` / `get_last_signal_payload` accepts a `params` kwarg, pass `entry["params_values"]`

4. `generator.py` — `_emit_module_constants()` extension
   - Current: emits flat constants (`EMA_14_PERIOD = 14`, etc.)
   - Required: also emit a `PARAMS` dict derived from `indicators[].params`

**Output**:

- A validated, merged `dict` mapping param-key → typed scalar value (int or float only)
- An augmented strategy entry dict with `params_schema: dict | None` and `params_values: dict`
- A modified `_analyze_strategy` that passes `params` kwarg when the strategy's signal function accepts it
- A `PARAMS` block emitted by the generator for Builder-generated strategies

**Constraints**:

- `n` (candle rows) = 500; the params mechanism adds zero DataFrame work — it is pure dict operations
- Called once per strategy per main loop tick (every 10 s) for the kwarg-detection path; detection result must be cached (not re-inspected every tick)
- `k` = 3 active strategies; total overhead is negligible if signature inspection is cached
- Types in v1: `"int"` and `"float"` only — no `"bool"`, `"str"`, `"enum"` at this stage
- Backward compatibility is a hard requirement: strategies without `PARAMS` and functions without `params` kwarg must behave identically to today

**Invariants**:

- `PARAMS`, if present, is a module-level `dict` declared by the strategy author (not injected)
- `.params.json` is the override store; it may be absent, partially populated, or fully absent
- Override values in `.params.json` are always within `[min, max]` (validated at write time by the GUI, TASK-043); the engine reads them as-is and does not re-validate
- `strategy_key` is stable per session (slugified, deduplicated in `load_active_strategies()`)
- Builder-generated `.py` files do not declare `PARAMS` today; the generator spec below adds it

**Clarity**: clear

---

## Candidate Algorithms

This task covers four distinct sub-problems. Each is analyzed separately.

---

### Sub-problem 1: Merge defaults + overrides from `.params.json`

#### Candidate A — Dict merge with `json.load` on each call
- **Description**: Every call to `_load_strategy_params` opens the `.params.json` file if it exists, parses it, then merges defaults from `PARAMS` with file overrides key-by-key.
- **Time**: O(p) where p = number of params (typically 1–10); plus one file I/O per call
- **Space**: O(p)
- **Verdict**: eliminated for the hot path (called every tick); acceptable only at load time
- **Reason**: File I/O at every 10-second tick is unnecessary. The `.params.json` changes only when the user edits params in the GUI. Re-reading on every tick would also introduce TOCTOU races if the GUI writes while the engine reads.

#### Candidate B — Load once at strategy registration; reload on explicit trigger
- **Description**: `_load_strategy_params` is called once during `load_active_strategies()` (i.e., at startup and on strategy reload). The result is stored in `entry["params_values"]`. The GUI triggers a strategy reload (already done via `importlib.reload`) when params change, which re-runs `_load_strategy_params`.
- **Time**: O(p) + one file I/O at load time only
- **Space**: O(p) per strategy entry (held in the entry dict in memory)
- **Verdict**: selected
- **Reason**: Matches the existing reload pattern: `load_active_strategies()` is already the single point where strategy modules are loaded/reloaded. Hooking params loading here requires zero new mechanism. The GUI's "save params" action will trigger the same reload path already used for `importlib.reload`.

---

### Sub-problem 2: Detect if `get_last_signal` / `get_last_signal_payload` accepts `params` kwarg

#### Candidate A — `inspect.signature()` on every `_analyze_strategy` call
- **Description**: Each call to `_analyze_strategy` calls `inspect.signature(fn)` and checks for `params` in `parameters`.
- **Time**: O(1) per call (CPython caches `__code__` signatures internally, but the Python-layer call still has overhead)
- **Space**: O(1)
- **Verdict**: eliminated
- **Reason**: `inspect.signature()` is not free — it involves attribute lookups and dict construction. Called every 10 s across 3 strategies in a ThreadPoolExecutor, it is unnecessary repeated work. The signature does not change between ticks.

#### Candidate B — Cache boolean flag in entry dict at load time
- **Description**: During `load_active_strategies()`, after the module loads, inspect the signature of `get_last_signal_payload` (preferred) or `get_last_signal` (fallback) once. Store the result as `entry["accepts_params"] = True | False`. `_analyze_strategy` reads this flag.
- **Time**: O(1) at load time; O(1) per tick (dict lookup)
- **Space**: O(1) per entry
- **Verdict**: selected
- **Reason**: Signature inspection cost is paid once. Lookup is a single boolean dict access at runtime. Correct for the lifetime of a module load (the signature cannot change without a reload, which re-runs the detection).

---

### Sub-problem 3: PARAMS schema validation (what fields are required/optional)

This is a data-modeling decision, not an algorithm selection in the computational sense. Two approaches:

#### Candidate A — Runtime validation via manual field checks
- **Description**: At load time, iterate `PARAMS` entries; for each, verify `type in {"int", "float"}`, `default` is present and matches type, `min` <= `default` <= `max`, `label` is a non-empty string.
- **Time**: O(p)
- **Space**: O(1)
- **Verdict**: selected
- **Reason**: v1 has exactly 5 fields and 2 types. A schema library (jsonschema, pydantic) would be a new dependency for trivial gain. Manual checks are readable, auditable, and add zero imports.

#### Candidate B — jsonschema / pydantic validation
- **Verdict**: eliminated
- **Reason**: New dependency for a 5-field dict. Overkill for v1 scope. Can be added later without breaking the API.

---

### Sub-problem 4: PARAMS block in generator.py

#### Candidate A — Emit a flat `PARAMS` dict by iterating `indicators[].params`
- **Description**: `_emit_module_constants()` (or a new `_emit_params_block()` helper) iterates all non-pre-computed indicators, collects their params, and emits a single `PARAMS = { ... }` dict at module level.
- **Time**: O(I * p) where I = number of indicators (typically 2–5), p = params per indicator (1–2)
- **Space**: O(I * p)
- **Verdict**: selected
- **Reason**: The existing `_emit_module_constants` already iterates indicators to emit flat constants. Adding `PARAMS` emission is a natural extension of the same loop. No structural change to the generator needed.

#### Candidate B — Derive PARAMS from the existing flat constants
- **Description**: Parse the already-emitted constant lines to reconstruct a PARAMS dict.
- **Verdict**: eliminated
- **Reason**: Roundabout and fragile. The source of truth is `indicators[].params` in the config dict, not the already-rendered string constants.

---

## Selected Algorithms (summary)

| Sub-problem | Winner |
|-------------|--------|
| Merge defaults + overrides | Load-once at registration (Candidate B) |
| Kwarg detection | Cache boolean flag at load time (Candidate B) |
| Schema validation | Manual field checks (Candidate A) |
| Generator PARAMS block | Flat dict emission from indicators (Candidate A) |

---

## Pseudocode Spec

### 1. PARAMS Schema

A valid `PARAMS` dict at module level has this structure:

```
PARAMS = {
    "<param_key>": {
        "label":   <str, non-empty>,
        "type":    <"int" | "float">,
        "default": <int or float matching "type">,
        "min":     <same type as default, <= default>,
        "max":     <same type as default, >= default>,
    },
    ...
}
```

Rules:
- `param_key`: non-empty string, no spaces (convention: snake_case)
- `type`: must be exactly `"int"` or `"float"` — any other value → entire `PARAMS` is rejected (treated as None)
- `default` type must match `type`: if `type == "int"`, default must be `isinstance(v, int) and not isinstance(v, bool)`; if `type == "float"`, default must be `isinstance(v, (int, float)) and not isinstance(v, bool)`
- `min <= default <= max` must hold
- Missing required fields → entry is skipped with a warning log; remaining entries are still processed
- `PARAMS` may be an empty dict `{}` — valid, means no editable params


### 2. `_validate_params_schema(raw_params) -> dict`

```
function _validate_params_schema(raw_params):
    # raw_params: any value retrieved via getattr(module, "PARAMS", None)
    # Returns: validated dict (may be empty) or None if raw_params is None

    if raw_params is None:
        return None

    if not isinstance(raw_params, dict):
        log warning: "PARAMS is not a dict — ignored"
        return None

    validated = {}
    for key, entry in raw_params.items():
        if not isinstance(key, str) or not key.strip():
            log warning: f"PARAMS key {key!r} invalid — skipped"
            continue
        if not isinstance(entry, dict):
            log warning: f"PARAMS[{key!r}] is not a dict — skipped"
            continue

        type_str = entry.get("type")
        if type_str not in ("int", "float"):
            log warning: f"PARAMS[{key!r}].type={type_str!r} invalid — skipped"
            continue

        default = entry.get("default")
        min_val = entry.get("min")
        max_val = entry.get("max")
        label   = entry.get("label", key)

        # type coercion
        try:
            if type_str == "int":
                default = int(default)
                min_val = int(min_val)
                max_val = int(max_val)
            else:  # float
                default = float(default)
                min_val = float(min_val)
                max_val = float(max_val)
        except (TypeError, ValueError):
            log warning: f"PARAMS[{key!r}] type coercion failed — skipped"
            continue

        if not (min_val <= default <= max_val):
            log warning: f"PARAMS[{key!r}] default {default} not in [{min_val}, {max_val}] — skipped"
            continue

        validated[key] = {
            "label":   str(label),
            "type":    type_str,
            "default": default,
            "min":     min_val,
            "max":     max_val,
        }

    return validated  # may be empty dict {}
```


### 3. `_load_strategy_params(module, strategy_key, strategies_dir) -> dict`

```
function _load_strategy_params(module, strategy_key, strategies_dir) -> dict:
    # Returns: merged params dict {key: value} using validated schema defaults + file overrides
    # Returns empty dict {} if module has no valid PARAMS

    raw_params = getattr(module, "PARAMS", None)
    schema = _validate_params_schema(raw_params)

    if schema is None or len(schema) == 0:
        return {}

    # Build defaults from schema
    merged = {key: entry["default"] for key, entry in schema.items()}

    # Locate companion .params.json
    # Companion lives next to the .py file, named "<strategy_key>.params.json"
    # Prefer module.__file__ to locate the .py; fall back to strategies_dir
    module_file = getattr(module, "__file__", None)
    if module_file and module_file != "<string>" and not module_file.startswith("<"):
        params_json_path = os.path.splitext(module_file)[0] + ".params.json"
    else:
        params_json_path = os.path.join(strategies_dir, strategy_key + ".params.json")

    if os.path.isfile(params_json_path):
        try:
            with open(params_json_path, "r", encoding="utf-8") as f:
                overrides = json.load(f)
            if isinstance(overrides, dict):
                for key, value in overrides.items():
                    if key not in schema:
                        continue  # ignore unknown keys
                    type_str = schema[key]["type"]
                    min_val  = schema[key]["min"]
                    max_val  = schema[key]["max"]
                    try:
                        if type_str == "int":
                            coerced = int(value)
                        else:
                            coerced = float(value)
                    except (TypeError, ValueError):
                        continue  # ignore unparseable override; keep default
                    # clamp to schema bounds (defensive; GUI validates at write time)
                    coerced = max(min_val, min(max_val, coerced))
                    merged[key] = coerced
        except (OSError, json.JSONDecodeError) as e:
            log warning: f"Could not read {params_json_path}: {e} — using defaults"

    return merged
    # Returns dict {param_key: typed_scalar}; always same keys as schema
```


### 4. `_detect_params_kwarg(module) -> bool`

```
function _detect_params_kwarg(module) -> bool:
    # Returns True if the strategy's signal function accepts a 'params' keyword argument.
    # Checks get_last_signal_payload first (preferred), then get_last_signal.
    # Returns False if neither exists or neither accepts 'params'.

    import inspect

    for fn_name in ("get_last_signal_payload", "get_last_signal"):
        fn = getattr(module, fn_name, None)
        if fn is None:
            continue
        try:
            sig = inspect.signature(fn)
        except (ValueError, TypeError):
            continue
        params_in_sig = sig.parameters
        if "params" in params_in_sig:
            return True
        # Also accept **kwargs as implicit acceptance
        for p in params_in_sig.values():
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                return True
        # Only check the first found function — do not check both
        return False

    return False
```


### 5. Extensions to `load_active_strategies()`

After the current block that appends an entry dict (approximately line 277 in main.py):

```
# --- existing entry append ---
entries.append({
    "key": key,
    "label": label or key,
    "module_ref": module_ref,
    "module": module,
    "timeframe_value": timeframe_value,
    "timeframe_label": _timeframe_label(timeframe_value) or "M1",
    "magic_override": entry_dict.get("magic_number") if isinstance(item, dict) else None,
    # NEW FIELDS:
    "params_schema":    <computed below>,
    "params_values":    <computed below>,
    "accepts_params":   <computed below>,
})

# Compute new fields immediately before or after module validation:
raw_params     = getattr(module, "PARAMS", None)
params_schema  = _validate_params_schema(raw_params)  # dict | None
params_values  = _load_strategy_params(module, key, strategies_dir)  # dict (may be {})
accepts_params = _detect_params_kwarg(module)          # bool
```

The fallback entry block (around line 315) must also be extended with the same three fields, applying the same three function calls.

Note: `strategies_dir` is already computed in `load_active_strategies()` as a local variable. No new parameter is needed.


### 6. Extension to `_analyze_strategy()`

```
function _analyze_strategy(index, entry, base_df):
    # ... existing setup and error checks ...

    strategy_df = _apply_strategy_processing(base_df, entry["module"])

    # NEW: determine params kwarg
    params_values  = entry.get("params_values") or {}
    accepts_params = entry.get("accepts_params", False)

    if accepts_params and params_values:
        signal_payload = runtime_get_strategy_signal_payload(
            strategy_df,
            entry["module"],
            verbose=False,
            params=params_values,          # passed through to the strategy fn
        )
    else:
        signal_payload = runtime_get_strategy_signal_payload(
            strategy_df,
            entry["module"],
            verbose=False,
        )

    # ... rest unchanged ...
```

`runtime_get_strategy_signal_payload` (in `strategy_runtime.py`) must also be updated to accept and forward the optional `params` kwarg to the strategy function. The updated signature:

```
function get_strategy_signal_payload(df, module, verbose=False, params=None) -> dict:
    # ... existing module None guard ...

    payload = None
    if hasattr(module, "get_last_signal_payload"):
        try:
            if params is not None:
                payload = module.get_last_signal_payload(df, verbose=verbose, params=params)
            else:
                payload = module.get_last_signal_payload(df, verbose=verbose)
        except TypeError:
            # Fallback: try without params kwarg (handles strategies that don't accept it)
            try:
                payload = module.get_last_signal_payload(df, verbose=verbose)
            except TypeError:
                payload = module.get_last_signal_payload(df)

    if payload is None and hasattr(module, "get_last_signal"):
        try:
            if params is not None:
                payload = module.get_last_signal(df, verbose=verbose, params=params)
            else:
                payload = module.get_last_signal(df, verbose=verbose)
        except TypeError:
            try:
                payload = module.get_last_signal(df, verbose=verbose)
            except TypeError:
                payload = module.get_last_signal(df)

    return normalize_signal_payload(payload)
```

Note: the `accepts_params` flag cached in the entry dict means the `TypeError` fallback path in `get_strategy_signal_payload` is a defensive layer only — it should never be exercised in the normal path. It protects against edge cases (e.g., module reloaded externally without going through `load_active_strategies`).


### 7. `_emit_params_block(indicators) -> str` in generator.py

This function is added to `strategy_builder/generator.py` and called from `render_strategy_source()` as a new section, inserted immediately after `_emit_module_constants()`.

```
function _emit_params_block(indicators) -> str:
    # indicators: list of indicator dicts from the strategy config
    # Returns: Python source string for the PARAMS module-level dict
    # Returns "" (empty string) if no non-pre-computed indicators have params

    entries = []

    for ind in indicators:
        if ind["pre_computed"]:
            continue
        ind_id = ind["id"]
        p      = ind["params"]  # dict of param_key -> value

        # Map each indicator type to its param entries
        # Each entry is: (param_key, label, type_str, default, min, max)

        if ind_id == "EMA":
            period = int(p["period"])
            entries.append((
                f"ema_{period}_period",
                f"EMA {period} Period",
                "int", period, 2, 500
            ))

        elif ind_id == "SMA":
            period = int(p["period"])
            entries.append((
                f"sma_{period}_period",
                f"SMA {period} Period",
                "int", period, 2, 500
            ))

        elif ind_id == "RSI":
            period = int(p["period"])
            entries.append((
                f"rsi_{period}_period",
                f"RSI {period} Period",
                "int", period, 2, 200
            ))

        elif ind_id == "BB":
            period = int(p["period"])
            mult   = float(p["multiplier"])
            entries.append((
                f"bb_{period}_period",
                f"BB {period} Period",
                "int", period, 2, 500
            ))
            entries.append((
                f"bb_{period}_mult",
                f"BB {period} Mult",
                "float", mult, 0.1, 10.0
            ))

        elif ind_id == "DONCHIAN":
            period = int(p["period"])
            entries.append((
                f"donchian_{period}_period",
                f"Donchian {period} Period",
                "int", period, 2, 500
            ))

        elif ind_id == "ATR":
            period = int(p["period"])
            entries.append((
                f"atr_{period}_period",
                f"ATR {period} Period",
                "int", period, 1, 200
            ))

        elif ind_id == "VOLUME_RATIO":
            lookback = int(p["lookback"])
            entries.append((
                f"volume_ratio_{lookback}_lookback",
                f"Volume Ratio {lookback} Lookback",
                "int", lookback, 2, 500
            ))

        elif ind_id == "ADX_DI":
            period = int(p["period"])
            entries.append((
                f"adx_di_{period}_period",
                f"ADX/DI {period} Period",
                "int", period, 2, 200
            ))

        # VWAP, HMA, SUPERTREND, TCI: no user-editable params → no entries

    if not entries:
        return ""

    lines = ["PARAMS = {"]
    for (key, label, type_str, default, min_val, max_val) in entries:
        lines.append(f'    "{key}": {{"label": "{label}", "type": "{type_str}", "default": {default!r}, "min": {min_val!r}, "max": {max_val!r}}},')
    lines.append("}")

    return "\n".join(lines)
```

Integration in `render_strategy_source()`:

```
sections = [
    _emit_docstring(display_name, description, timeframe),
    "import pandas as pd",
    _emit_module_constants(timeframe, magic_number, indicators),
    _emit_params_block(indicators),                     # NEW — after constants
    _emit_strategy_object_tree_items(indicators),
    _emit_data_window_fields(indicators),
    _emit_helper_functions(indicators),
    ...
]
```

`_emit_params_block` returns `""` when there are no params, and the existing `"\n\n".join(s for s in sections if s)` filter already handles empty strings — no change needed to the join logic.

---

## Behavioral Guarantees (No-Op Paths)

### Module without `PARAMS`

```
getattr(module, "PARAMS", None)  →  None
_validate_params_schema(None)    →  None
_load_strategy_params(...)       →  {}
entry["params_schema"]           =  None
entry["params_values"]           =  {}
entry["accepts_params"]          =  False  (or True if fn signature has params kwarg)
```

`_analyze_strategy` calls `runtime_get_strategy_signal_payload` without `params` kwarg.
Behavior is identical to current.

### Module with `PARAMS` but function without `params` kwarg

```
entry["params_schema"]  = <validated schema>
entry["params_values"]  = <merged values>
entry["accepts_params"] = False
```

`_analyze_strategy` sees `accepts_params == False` → calls without `params`.
Strategy function receives exactly what it receives today.
Behavior is identical to current.

### Module with `PARAMS` and function with `params` kwarg

```
entry["accepts_params"] = True
```

`_analyze_strategy` passes `params=entry["params_values"]` to `runtime_get_strategy_signal_payload`, which forwards it to the strategy function.
This is the new behavior path; only strategies that explicitly opt in via kwarg declaration receive it.

---

## Notes for Implementing Agents (Alex / Felix)

- Alex implements: `_validate_params_schema`, `_load_strategy_params`, `_detect_params_kwarg`, extensions to `load_active_strategies()`, extensions to `_analyze_strategy()`, and `get_strategy_signal_payload` update in `strategy_runtime.py`. All in TASK-044.
- Felix implements: `_emit_params_block` in `generator.py` and its integration in `render_strategy_source()`. Also in TASK-044.
- Grace specs the GUI panel in TASK-043 using `entry["params_schema"]` and `entry["params_values"]` as the data source. The GUI writes overrides to `<strategy_key>.params.json` alongside the `.py` file, then triggers a strategy reload.
- The `.params.json` file location: same directory as the strategy `.py` file, named `<stem>.params.json` (where stem = the `.py` filename without extension). Example: `strategies/strategy_primera_estrategia.params.json`. This is consistent with how the Builder companion `.json` lives next to the `.py`.
- `strategies_dir` is already a local variable in `load_active_strategies()` — no API change needed to pass it to `_load_strategy_params`.
