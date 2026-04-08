"""
strategies/builder.py — Strategy Builder generator module.

Provides generate_strategy_file() — the entry point that receives a validated
StrategyConfig dict and writes strategies/strategy_<name>.py + strategy_<name>.json.

All pseudocode source: agents/specs/TASK-014c-strategy-data-model-and-generator.md
Condition tree model: agents/specs/TASK-014b-condition-tree-model.md

This module is NOT imported by generated strategies (isolation rule).
"""

import ast
import json
import random
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STRATEGIES_DIR = Path(__file__).parent

ALLOWED_OPERATORS = {"<", ">", "<=", ">=", "==", "!="}

ALWAYS_AVAILABLE_COLUMNS = {
    "open", "high", "low", "close", "OHLC4", "HLC3", "HL2",
    "tick_volume", "average", "atr", "upper", "lower",
    "hma", "supertrend", "supertrend_dir", "supertrend_up", "supertrend_down",
    "tci", "tci_signal", "tci_hist",
}

VALID_TIMEFRAMES = {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}

VALID_INDICATOR_IDS = {
    "EMA", "RSI", "BB", "DONCHIAN", "ATR", "VWAP",
    "VOLUME_RATIO", "SMA", "HMA", "SUPERTREND", "TCI",
    "ADX_DI",
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    pass


class NameCollisionError(ValidationError):
    pass


class GeneratorError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def generate_strategy_file(config: dict, strategies_dir: Path = None, is_new: bool = True) -> Path:
    """
    Write strategies/strategy_<name>.py and strategy_<name>.json.

    Precondition: config has already passed validate_strategy_config().
    Returns the path to the written .py file.
    Raises GeneratorError if code generation or file write fails.
    """
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    name = config["name"]
    display_name = config["display_name"]
    description = config.get("description", "")
    timeframe = config["timeframe"]
    magic_number = config["magic_number"]
    indicators = config["indicators"]
    buy_cond = config["buy_condition"]
    sell_cond = config["sell_condition"]

    # Derived metadata
    custom_indicators = [ind for ind in indicators if not ind["pre_computed"]]
    needs_prepare = len(custom_indicators) > 0
    needs_volume = any(ind["id"] in ("VWAP", "VOLUME_RATIO") for ind in custom_indicators)
    needs_high_low = any(ind["id"] in ("DONCHIAN", "ATR", "VWAP", "ADX_DI") for ind in custom_indicators)
    needs_close = any(
        ind["id"] in ("EMA", "RSI", "BB", "ATR", "VWAP", "VOLUME_RATIO", "SMA", "ADX_DI")
        for ind in custom_indicators
    )

    condition_columns = _collect_leaf_columns(buy_cond) | _collect_leaf_columns(sell_cond)

    # Assemble sections
    sections = [
        _emit_docstring(display_name, description, timeframe),
        "import pandas as pd",
        _emit_module_constants(timeframe, magic_number, indicators),
        _emit_data_window_fields(indicators),
        _emit_helper_functions(indicators),
    ]

    if needs_prepare:
        sections.append(
            _emit_prepare_dataframe(custom_indicators, needs_close, needs_high_low, needs_volume)
        )

    payload_extra = config.get("payload_extra_fields", [])
    sections.append(_emit_compute_signals(buy_cond, sell_cond, condition_columns))
    sections.append(_emit_get_last_signal_payload(display_name, payload_extra))
    sections.append(_emit_get_last_signal(buy_cond, sell_cond))

    py_content = "\n\n".join(s for s in sections if s) + "\n"

    # Final syntax check — mandatory before writing any file
    try:
        ast.parse(py_content)
    except SyntaxError as exc:
        raise GeneratorError(f"Generated code failed ast.parse: {exc}") from exc

    py_path = strategies_dir / f"strategy_{name}.py"
    json_path = strategies_dir / f"strategy_{name}.json"

    _write_atomic(py_path, py_content)
    _write_atomic(json_path, json.dumps(config, indent=2, ensure_ascii=False))

    return py_path


def handle_save_new(raw_config: dict, strategies_dir: Path = None) -> Path:
    """
    Full create flow: sanitize name, check collisions, assign magic_number, validate, generate.
    Returns path to the written .py file.
    """
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    raw_config["name"] = sanitize_name(raw_config.get("display_name", ""), strategies_dir)
    name = raw_config["name"]
    py_path = strategies_dir / f"strategy_{name}.py"
    json_path = strategies_dir / f"strategy_{name}.json"

    if py_path.exists() and not json_path.exists():
        raise NameCollisionError(
            f"A hand-crafted strategy named '{name}' already exists."
        )
    if py_path.exists() and json_path.exists():
        raise NameCollisionError(
            f"A Builder strategy named '{name}' already exists. Use Edit to modify it."
        )

    raw_config["magic_number"] = generate_magic_number()
    raw_config["schema_version"] = 1

    validate_strategy_config(raw_config, is_new=True, strategies_dir=strategies_dir)
    return generate_strategy_file(raw_config, strategies_dir=strategies_dir, is_new=True)


def handle_save_edit(raw_config: dict, original_name: str, strategies_dir: Path = None) -> Path:
    """
    Full edit flow: preserve magic_number, handle rename, validate, generate, remove old files.
    Returns path to the written .py file.
    """
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    stored_json_path = strategies_dir / f"strategy_{original_name}.json"
    stored_config = json.loads(stored_json_path.read_text(encoding="utf-8"))
    preserved_magic = stored_config["magic_number"]

    new_name = sanitize_name(raw_config.get("display_name", ""), strategies_dir,
                             exclude_name=original_name)
    raw_config["name"] = new_name
    raw_config["magic_number"] = preserved_magic
    raw_config["schema_version"] = 1

    if new_name != original_name:
        new_py = strategies_dir / f"strategy_{new_name}.py"
        if new_py.exists():
            raise NameCollisionError(f"Name '{new_name}' is already taken.")

    validate_strategy_config(raw_config, is_new=False, strategies_dir=strategies_dir)
    py_path = generate_strategy_file(raw_config, strategies_dir=strategies_dir, is_new=False)

    if new_name != original_name:
        old_py = strategies_dir / f"strategy_{original_name}.py"
        old_json = strategies_dir / f"strategy_{original_name}.json"
        if old_py.exists():
            old_py.unlink()
        if old_json.exists():
            old_json.unlink()

    return py_path


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_strategy_config(
    config: dict, is_new: bool = True, strategies_dir: Path = None
) -> None:
    """
    Validate a StrategyConfig dict. Raises ValidationError on any failure.
    Mutates config in-place for coercions (period → int, deduplication).
    May print warnings for non-blocking issues.
    """
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    # Required top-level fields
    required_keys = {
        "schema_version", "name", "display_name", "timeframe",
        "magic_number", "indicators", "buy_condition", "sell_condition",
    }
    missing = required_keys - set(config.keys())
    if missing:
        raise ValidationError(f"Missing required fields: {sorted(missing)}")

    # schema_version
    if config["schema_version"] != 1:
        raise ValidationError(f"Unsupported schema_version: {config['schema_version']}")

    # name
    name = config["name"]
    if not re.match(r'^[a-z][a-z0-9_]*$', name):
        raise ValidationError(
            f"Invalid strategy name '{name}'. Use lowercase letters, digits, underscores only."
        )

    py_path = strategies_dir / f"strategy_{name}.py"
    json_path = strategies_dir / f"strategy_{name}.json"

    if is_new:
        if py_path.exists() and not json_path.exists():
            raise ValidationError(
                "A hand-crafted strategy with this name already exists."
            )
        if py_path.exists() and json_path.exists():
            raise ValidationError(
                "A Builder strategy with this name already exists. Use Edit to modify it."
            )

    # display_name
    display_name = config.get("display_name", "")
    if not display_name or len(display_name) > 80:
        raise ValidationError("display_name must be 1–80 characters.")

    # description
    desc = config.get("description", "")
    if len(desc) > 500:
        raise ValidationError("description must be ≤ 500 characters.")

    # timeframe
    if config["timeframe"] not in VALID_TIMEFRAMES:
        raise ValidationError(
            f"Invalid timeframe '{config['timeframe']}'. Must be one of {sorted(VALID_TIMEFRAMES)}."
        )

    # magic_number
    magic = config["magic_number"]
    if not isinstance(magic, int) or not (10000 <= magic <= 99999):
        raise ValidationError("magic_number must be an integer in range 10000–99999.")

    # indicators — coerce params, deduplicate
    indicators = config.get("indicators", [])
    for ind in indicators:
        if ind["id"] not in VALID_INDICATOR_IDS:
            raise ValidationError(f"Unknown indicator id '{ind['id']}'.")
        p = ind.get("params", {})
        if "period" in p:
            p["period"] = int(p["period"])
        if "lookback" in p:
            p["lookback"] = int(p["lookback"])

    # Deduplicate (silent, keeps first occurrence)
    seen: dict = {}
    deduped = []
    for ind in indicators:
        key = (ind["id"], json.dumps(ind.get("params", {}), sort_keys=True))
        if key not in seen:
            seen[key] = True
            deduped.append(ind)
    config["indicators"] = deduped

    # Build available column set
    available = ALWAYS_AVAILABLE_COLUMNS.copy()
    for ind in config["indicators"]:
        available.update(ind.get("columns", []))

    # Condition tree validation
    _validate_condition_node(config["buy_condition"], available, "buy_condition")
    _validate_condition_node(config["sell_condition"], available, "sell_condition")

    # Identical buy/sell warning
    if (json.dumps(config["buy_condition"], sort_keys=True) ==
            json.dumps(config["sell_condition"], sort_keys=True)):
        print(
            "WARNING: Buy and sell conditions are identical "
            "— strategy will always trade buy on conflict."
        )

    # VWAP on D1 warning
    has_vwap = any(ind["id"] == "VWAP" for ind in config["indicators"])
    if has_vwap and config["timeframe"] == "D1":
        print("WARNING: VWAP is not meaningful on D1 timeframe.")


def _validate_condition_node(node: dict, available_columns: set, path: str) -> None:
    node_type = node.get("type")

    if node_type == "condition":
        left = node.get("left")
        if left not in available_columns:
            raise ValidationError(
                f"{path}: column '{left}' not available. Add the corresponding indicator."
            )
        right = node.get("right")
        if isinstance(right, str) and right not in available_columns:
            raise ValidationError(
                f"{path}: column '{right}' (right operand) not available. "
                f"Add the corresponding indicator."
            )
        op = node.get("op")
        if op not in ALLOWED_OPERATORS:
            raise ValidationError(f"{path}: invalid operator '{op}'.")

    elif node_type in ("AND", "OR"):
        children = node.get("children", [])
        if len(children) < 2:
            raise ValidationError(
                f"{path}: group must contain at least 2 conditions (found {len(children)})."
            )
        for i, child in enumerate(children):
            _validate_condition_node(child, available_columns, f"{path}.children[{i}]")

    else:
        raise ValidationError(f"{path}: unknown node type '{node_type}'.")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def generate_magic_number() -> int:
    """Return a random 5-digit magic number (10000–99999)."""
    return random.randint(10000, 99999)


def sanitize_name(display_name: str, strategies_dir: Path = None, exclude_name: str = None) -> str:
    """
    Convert a user-visible display name to a valid machine name.
    Appends _2, _3, ... if the name is already taken (excluding exclude_name).
    """
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    s = display_name.lower()
    s = re.sub(r'[^a-z0-9_]', '_', s)
    s = re.sub(r'_+', '_', s)
    s = s.strip('_')
    if not s or s[0].isdigit():
        s = 'strategy_' + s

    base = s
    candidate = base
    suffix = 2
    while True:
        py_path = strategies_dir / f"strategy_{candidate}.py"
        if not py_path.exists() or candidate == exclude_name:
            break
        candidate = f"{base}_{suffix}"
        suffix += 1

    return candidate


def _write_atomic(path: Path, content: str) -> None:
    """Write content to path atomically via a .tmp file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _collect_leaf_columns(node: dict) -> set:
    """Recursively collect all column name references from a condition tree."""
    cols: set = set()
    if node["type"] == "condition":
        cols.add(node["left"])
        right = node["right"]
        if isinstance(right, str):
            cols.add(right)
    else:
        for child in node.get("children", []):
            cols |= _collect_leaf_columns(child)
    return cols


# ---------------------------------------------------------------------------
# Condition emitters
# ---------------------------------------------------------------------------


def emit_condition(node: dict) -> str:
    """
    Scalar emitter (TASK-014b): produces df.iloc[-2]["col"] expressions.
    Used in get_last_signal.
    """
    node_type = node["type"]

    if node_type == "condition":
        left_expr = f'df.iloc[-2]["{node["left"]}"]'
        right = node["right"]
        if isinstance(right, (int, float)):
            if isinstance(right, float) and right == int(right):
                right_expr = str(int(right))
            else:
                right_expr = repr(right)
        else:
            right_expr = f'df.iloc[-2]["{right}"]'
        return f"{left_expr} {node['op']} {right_expr}"

    elif node_type in ("AND", "OR"):
        connector = " and " if node_type == "AND" else " or "
        child_exprs = [emit_condition(child) for child in node["children"]]
        return "(" + connector.join(child_exprs) + ")"

    else:
        raise ValueError(f"emit_condition: unknown node type '{node_type}'")


def _emit_vectorized_condition(node: dict) -> str:
    """
    Vectorized emitter (TASK-014c §4.7): produces pandas boolean Series expressions.
    Used in compute_signals.
    """
    node_type = node["type"]

    if node_type == "condition":
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

    elif node_type in ("AND", "OR"):
        connector = " & " if node_type == "AND" else " | "
        child_exprs = [_emit_vectorized_condition(child) for child in node["children"]]
        return "(" + connector.join(child_exprs) + ")"

    else:
        raise ValueError(f"_emit_vectorized_condition: unknown node type '{node_type}'")


# ---------------------------------------------------------------------------
# Section emitters
# ---------------------------------------------------------------------------


def _emit_docstring(display_name: str, description: str, timeframe: str) -> str:
    desc_line = f"\n{description}" if description else ""
    return (
        f'"""\n{display_name} — {timeframe}{desc_line}\n'
        f'Generated by Strategy Builder. Edit via the Builder UI, not this file.\n"""'
    )


def _emit_module_constants(timeframe: str, magic_number: int, indicators: list) -> str:
    lines = [
        f'TIMEFRAME = "{timeframe}"',
        f'MAGIC_NUMBER = {magic_number}',
    ]

    for ind in indicators:
        if ind["pre_computed"]:
            continue
        ind_id = ind["id"]
        p = ind["params"]

        if ind_id == "EMA":
            period = int(p["period"])
            lines.append(f"EMA_{period}_PERIOD = {period}")
        elif ind_id == "RSI":
            period = int(p["period"])
            lines.append(f"RSI_{period}_PERIOD = {period}")
        elif ind_id == "BB":
            period = int(p["period"])
            mult = p["multiplier"]
            lines.append(f"BB_{period}_PERIOD = {period}")
            lines.append(f"BB_{period}_MULT = {mult}")
        elif ind_id == "DONCHIAN":
            period = int(p["period"])
            lines.append(f"DONCHIAN_{period}_PERIOD = {period}")
        elif ind_id == "ATR":
            period = int(p["period"])
            lines.append(f"ATR_{period}_PERIOD = {period}")
        elif ind_id == "VOLUME_RATIO":
            lookback = int(p["lookback"])
            lines.append(f"VOLUME_RATIO_{lookback}_LOOKBACK = {lookback}")
        elif ind_id == "SMA":
            period = int(p["period"])
            lines.append(f"SMA_{period}_PERIOD = {period}")
        elif ind_id == "ADX_DI":
            period = int(p["period"])
            lines.append(f"ADX_DI_{period}_PERIOD = {period}")
        # VWAP, HMA, SUPERTREND, TCI: no user params → no constants

    return "\n".join(lines)


def _emit_data_window_fields(indicators: list) -> str:
    entries = []

    for ind in indicators:
        ind_id = ind["id"]
        p = ind.get("params", {})

        if ind_id == "EMA":
            period = int(p["period"])
            entries.append(
                f'{{"key": "ema_{period}", "label": "EMA ({period})", "format": "price", "section": "Trend"}}'
            )
        elif ind_id == "RSI":
            period = int(p["period"])
            entries.append(
                f'{{"key": "rsi_{period}", "label": "RSI ({period})", "format": "number", "section": "Momentum"}}'
            )
        elif ind_id == "BB":
            period = int(p["period"])
            entries.append(
                f'{{"key": "bb_basis_{period}", "label": "BB Basis ({period})", "format": "price", "section": "Bollinger"}}'
            )
            entries.append(
                f'{{"key": "bb_upper_{period}", "label": "BB Upper ({period})", "format": "price", "section": "Bollinger"}}'
            )
            entries.append(
                f'{{"key": "bb_lower_{period}", "label": "BB Lower ({period})", "format": "price", "section": "Bollinger"}}'
            )
            entries.append(
                f'{{"key": "bb_width_pct_{period}", "label": "BB Width % ({period})", "format": "percent", "section": "Bollinger"}}'
            )
        elif ind_id == "DONCHIAN":
            period = int(p["period"])
            entries.append(
                f'{{"key": "donchian_high_{period}", "label": "Donchian High ({period})", "format": "price", "section": "Donchian"}}'
            )
            entries.append(
                f'{{"key": "donchian_low_{period}", "label": "Donchian Low ({period})", "format": "price", "section": "Donchian"}}'
            )
            entries.append(
                f'{{"key": "donchian_mid_{period}", "label": "Donchian Mid ({period})", "format": "price", "section": "Donchian"}}'
            )
        elif ind_id == "ATR":
            period = int(p["period"])
            entries.append(
                f'{{"key": "atr_{period}", "label": "ATR ({period})", "format": "price", "section": "Volatility"}}'
            )
            entries.append(
                f'{{"key": "atr_pct_{period}", "label": "ATR % ({period})", "format": "percent", "section": "Volatility"}}'
            )
        elif ind_id == "VWAP":
            entries.append('{"key": "vwap", "label": "VWAP", "format": "price", "section": "VWAP"}')
        elif ind_id == "VOLUME_RATIO":
            lookback = int(p["lookback"])
            entries.append(
                f'{{"key": "volume_ratio_{lookback}", "label": "Volume Ratio ({lookback})", "format": "number", "section": "Volume"}}'
            )
        elif ind_id == "SMA":
            period = int(p["period"])
            entries.append(
                f'{{"key": "sma_{period}", "label": "SMA ({period})", "format": "price", "section": "Trend"}}'
            )
        elif ind_id == "HMA":
            entries.append('{"key": "hma", "label": "HMA (55)", "format": "price", "section": "Trend"}')
        elif ind_id == "SUPERTREND":
            entries.append(
                '{"key": "supertrend_dir", "label": "Supertrend Dir", "format": "number", "section": "Supertrend"}'
            )
            entries.append(
                '{"key": "supertrend", "label": "Supertrend", "format": "price", "section": "Supertrend"}'
            )
        elif ind_id == "TCI":
            entries.append('{"key": "tci", "label": "TCI", "format": "number", "section": "TCI"}')
            entries.append(
                '{"key": "tci_signal", "label": "TCI Signal", "format": "number", "section": "TCI"}'
            )
            entries.append(
                '{"key": "tci_hist", "label": "TCI Hist", "format": "number", "section": "TCI"}'
            )
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

    # Always-last: signal columns
    entries.append(
        '{"key": "up_sig", "label": "Buy Signal", "format": "int", "section": "Signals", "shift": 1}'
    )
    entries.append(
        '{"key": "dn_sig", "label": "Sell Signal", "format": "int", "section": "Signals", "shift": 1}'
    )

    inner = ",\n    ".join(entries)
    return f"DATA_WINDOW_FIELDS = [\n    {inner},\n]"


_TEMPLATE_NUMERIC = """\
def _numeric(df: pd.DataFrame, key: str) -> pd.Series:
    return pd.to_numeric(df.get(key), errors="coerce")"""

_TEMPLATE_VOLUME_SERIES = """\
def _volume_series(df: pd.DataFrame) -> pd.Series:
    if "tick_volume" in df.columns:
        return pd.to_numeric(df.get("tick_volume"), errors="coerce")
    if "volume" in df.columns:
        return pd.to_numeric(df.get("volume"), errors="coerce")
    return pd.Series(1.0, index=df.index, dtype="float64")"""

_TEMPLATE_RSI = """\
def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0.0)
    loss     = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))"""

_TEMPLATE_ATR = """\
def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low,
         (high - prev_close).abs(),
         (low  - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()"""

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

_TEMPLATE_INTRADAY_VWAP = """\
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
    return cum_wp / cum_vol"""


def _emit_helper_functions(indicators: list) -> str:
    custom_ids = {ind["id"] for ind in indicators if not ind["pre_computed"]}

    blocks = [_TEMPLATE_NUMERIC]

    if "VWAP" in custom_ids or "VOLUME_RATIO" in custom_ids:
        blocks.append(_TEMPLATE_VOLUME_SERIES)
    if "RSI" in custom_ids:
        blocks.append(_TEMPLATE_RSI)
    if "ATR" in custom_ids:
        blocks.append(_TEMPLATE_ATR)
    if "VWAP" in custom_ids:
        blocks.append(_TEMPLATE_INTRADAY_VWAP)
    if "ADX_DI" in custom_ids:
        blocks.append(_TEMPLATE_ADX_DI)

    return "\n\n".join(blocks)


def _emit_indicator_computation_block(ind: dict) -> list:
    ind_id = ind["id"]
    p = ind.get("params", {})

    if ind_id == "EMA":
        period = int(p["period"])
        return [f"    ema_{period} = close.ewm(span={period}, adjust=False).mean()"]

    elif ind_id == "RSI":
        period = int(p["period"])
        return [f"    rsi_{period} = _rsi(close, {period})"]

    elif ind_id == "BB":
        period = int(p["period"])
        mult = p["multiplier"]
        return [
            f"    bb_basis_{period}     = close.rolling({period}, min_periods={period}).mean()",
            f"    bb_std_{period}       = close.rolling({period}, min_periods={period}).std(ddof=0)",
            f"    bb_upper_{period}     = bb_basis_{period} + (bb_std_{period} * {mult})",
            f"    bb_lower_{period}     = bb_basis_{period} - (bb_std_{period} * {mult})",
            f"    bb_width_pct_{period} = (bb_upper_{period} - bb_lower_{period}) / bb_basis_{period}.replace(0.0, float('nan'))",
        ]

    elif ind_id == "DONCHIAN":
        period = int(p["period"])
        return [
            f"    donchian_high_{period} = high.rolling({period}, min_periods={period}).max().shift(1)",
            f"    donchian_low_{period}  = low.rolling({period}, min_periods={period}).min().shift(1)",
            f"    donchian_mid_{period}  = (donchian_high_{period} + donchian_low_{period}) / 2.0",
        ]

    elif ind_id == "ATR":
        period = int(p["period"])
        return [
            f"    atr_{period}     = _atr(high, low, close, {period})",
            f"    atr_pct_{period} = atr_{period} / close.replace(0.0, float('nan'))",
        ]

    elif ind_id == "VWAP":
        return ["    vwap = _intraday_vwap(out, high, low, close, volume)"]

    elif ind_id == "VOLUME_RATIO":
        lookback = int(p["lookback"])
        return [
            f"    vol_ma_{lookback}       = volume.rolling({lookback}, min_periods=5).mean()",
            f"    volume_ratio_{lookback} = volume / vol_ma_{lookback}.replace(0.0, float('nan'))",
        ]

    elif ind_id == "SMA":
        period = int(p["period"])
        return [f"    sma_{period} = close.rolling({period}, min_periods={period}).mean()"]

    elif ind_id == "ADX_DI":
        period = int(p["period"])
        return [
            f"    adx_{period}, plus_di_{period}, minus_di_{period}, "
            f"plus_di_cross_{period}, minus_di_cross_{period} = "
            f"_adx_di(high, low, close, {period})",
        ]

    else:
        raise ValueError(f"_emit_indicator_computation_block: unknown id '{ind_id}'")


def _emit_prepare_dataframe(
    custom_indicators: list, needs_close: bool, needs_high_low: bool, needs_volume: bool
) -> str:
    required: set = set()
    if needs_close:
        required.add("close")
    if needs_high_low:
        required.update({"high", "low"})

    required_repr = "{" + ", ".join(repr(c) for c in sorted(required)) + "}"

    body = [
        "    out = df.copy()",
        f"    required = {required_repr}",
        "    if not required.issubset(out.columns):",
        "        return out",
    ]

    if needs_close:
        body.append('    close = _numeric(out, "close")')
    if needs_high_low:
        body.append('    high  = _numeric(out, "high")')
        body.append('    low   = _numeric(out, "low")')
    if needs_volume:
        body.append("    volume = _volume_series(out)")

    for ind in custom_indicators:
        body.extend(_emit_indicator_computation_block(ind))

    for ind in custom_indicators:
        for col in ind["columns"]:
            # Skip intermediate variables (bb_std_*, vol_ma_*) which are not in columns
            body.append(f'    out["{col}"] = {col}')

    body.append("    return out")

    return "def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:\n" + "\n".join(body)


def _emit_compute_signals(
    buy_condition: dict, sell_condition: dict, condition_columns: set
) -> str:
    buy_vec_expr = _emit_vectorized_condition(buy_condition)
    sell_vec_expr = _emit_vectorized_condition(sell_condition)

    needed_repr = "{" + ", ".join(repr(c) for c in sorted(condition_columns)) + "}"

    return (
        f"def compute_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:\n"
        f"    out = df.copy()\n"
        f"    needed = {needed_repr}\n"
        f"    if not needed.issubset(out.columns):\n"
        f'        out["long_setup"]  = 0\n'
        f'        out["short_setup"] = 0\n'
        f'        out["up_sig"]      = 0\n'
        f'        out["dn_sig"]      = 0\n'
        f"        return out\n"
        f"\n"
        f"    if enable_signals:\n"
        f"        buy_signal  = {buy_vec_expr}\n"
        f"        sell_signal = {sell_vec_expr}\n"
        f"    else:\n"
        f"        buy_signal  = pd.Series(False, index=out.index)\n"
        f"        sell_signal = pd.Series(False, index=out.index)\n"
        f"\n"
        f'    out["long_setup"]  = buy_signal.astype(int)\n'
        f'    out["short_setup"] = sell_signal.astype(int)\n'
        f'    out["up_sig"]      = buy_signal.astype(int)\n'
        f'    out["dn_sig"]      = sell_signal.astype(int)\n'
        f"    return out"
    )


def _emit_get_last_signal_payload(display_name: str, extra_fields: list = None) -> str:
    """
    Emit get_last_signal_payload.

    extra_fields: optional list of dicts, each with:
        {"key": str, "type": "literal"|"column", "value": ...}
    "literal" → value is emitted as a Python literal (True/False/int/float/str)
    "column"  → value is a column name → df.iloc[-2]["col_name"]
    """
    dn = display_name.replace('"', '\\"')

    extra_lines = ""
    if extra_fields:
        for field in extra_fields:
            key = field["key"]
            if field["type"] == "literal":
                val = repr(field["value"])
            else:
                col = field["value"]
                val = f'df.iloc[-2]["{col}"]'
            extra_lines += f',\n        "{key}": {val}'

    return (
        f"def get_last_signal_payload(df: pd.DataFrame, verbose: bool = False) -> dict:\n"
        f"    signal = get_last_signal(df, verbose=verbose)\n"
        f"    reasons = {{\n"
        f'        "buy":  "{dn}: buy condition met",\n'
        f'        "sell": "{dn}: sell condition met",\n'
        f'        "none": "{dn}: no signal",\n'
        f"    }}\n"
        f'    return {{"signal": signal, "reason": reasons[signal]{extra_lines}}}'
    )


def _emit_get_last_signal(buy_condition: dict, sell_condition: dict) -> str:
    buy_expr = emit_condition(buy_condition)
    sell_expr = emit_condition(sell_condition)

    return (
        f"def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:\n"
        f"    if df is None or len(df) < 3:\n"
        f'        return "none"\n'
        f"    if {buy_expr}:\n"
        f'        return "buy"\n'
        f"    elif {sell_expr}:\n"
        f'        return "sell"\n'
        f'    return "none"'
    )
