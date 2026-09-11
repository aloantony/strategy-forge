# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.
"""
backend/strategy_builder/generator.py — Strategy Builder generator module.

Provides generate_strategy_file() — the entry point that receives a validated
StrategyConfig dict and writes strategies/strategy_<name>.py + strategy_<name>.json.

Indicator catalogue and condition tree model: backend/strategy_builder/indicators.py.

This module is NOT imported by generated strategies (isolation rule).

Known limitation: the generated PARAMS block is declarative only — the generated
signal functions do not accept a `params` kwarg, and indicator periods are baked
into column names (ema_9, rsi_14...), so `.params.json` overrides have no effect
on Builder strategies. Changing parameters means re-saving via the Builder.
"""

import ast
import copy
import json
import logging
import random
import re
import types
from pathlib import Path

from backend.runtime.timeframes import TIMEFRAME_MINUTES
from backend.strategy_builder import indicators as ind_registry
from backend.strategy_builder.indicators import INDICATOR_SPECS, VALID_INDICATOR_IDS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent / "strategies"

ALLOWED_OPERATORS = {"<", ">", "<=", ">=", "==", "!="}

ALWAYS_AVAILABLE_COLUMNS = {
    "open", "high", "low", "close", "OHLC4", "HLC3", "HL2",
    "tick_volume", "average", "atr", "upper", "lower",
    "hma", "supertrend", "supertrend_dir", "supertrend_up", "supertrend_down",
    "tci", "tci_signal", "tci_hist",
}

VALID_TIMEFRAMES = set(TIMEFRAME_MINUTES)

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

    if _is_mtf_config(config):
        from backend.strategy_builder.mtf_generator import generate_mtf_strategy_file
        return generate_mtf_strategy_file(config, strategies_dir=strategies_dir)

    py_content = render_strategy_source(config)

    name = config["name"]

    py_path = strategies_dir / f"strategy_{name}.py"
    json_path = strategies_dir / f"strategy_{name}.json"

    _write_atomic(py_path, py_content)
    _write_atomic(json_path, json.dumps(config, indent=2, ensure_ascii=False))

    return py_path


def render_strategy_source(config: dict) -> str:
    """Render a validated StrategyConfig into Python source code."""
    if _is_mtf_config(config):
        from backend.strategy_builder.mtf_generator import render_mtf_strategy_source
        return render_mtf_strategy_source(config)

    name = config["name"]
    if not name:
        raise GeneratorError("Strategy name is required to render source.")

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
    needs = ind_registry.needed_series(custom_indicators)
    needs_volume = "volume" in needs
    needs_high_low = "high" in needs or "low" in needs
    needs_close = "close" in needs

    condition_columns = _collect_leaf_columns(buy_cond) | _collect_leaf_columns(sell_cond)

    # Assemble sections
    sections = [
        _emit_docstring(display_name, description, timeframe),
        "import pandas as pd",
        _emit_module_constants(timeframe, magic_number, indicators),
        _emit_params_block(indicators),
        _emit_strategy_object_tree_items(indicators),
        _emit_data_window_fields(indicators),
        _emit_helper_functions(indicators),
    ]

    if needs_prepare:
        sections.append(
            _emit_prepare_dataframe(indicators, custom_indicators, needs_close, needs_high_low, needs_volume)
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

    return py_content


def build_strategy_module(
    config: dict,
    strategies_dir: Path = None,
    is_new: bool = False,
    module_name: str = "strategy_builder_preview",
):
    """
    Build an in-memory strategy module from config.

    Useful for Builder previews without writing files to disk.
    """
    preview_config = copy.deepcopy(config)
    preview_config["schema_version"] = _requested_schema_version(preview_config)
    if _is_mtf_config(preview_config):
        from backend.strategy_builder.mtf_generator import validate_mtf_strategy_config
        validate_mtf_strategy_config(preview_config, is_new=is_new, strategies_dir=strategies_dir)
    else:
        validate_strategy_config(preview_config, is_new=is_new, strategies_dir=strategies_dir)
    py_content = render_strategy_source(preview_config)

    module = types.ModuleType(module_name)
    module.__file__ = f"<{module_name}>"
    exec(compile(py_content, module.__file__, "exec"), module.__dict__)
    return module


def handle_save_new(raw_config: dict, strategies_dir: Path = None) -> Path:
    """
    Full create flow: sanitize name, check collisions, assign magic_number, validate, generate.
    Returns path to the written .py file.
    """
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    raw_config = dict(raw_config)
    # sanitize_name auto-sufija (_2, _3...) hasta encontrar nombre libre, así que
    # aquí nunca hay colisión. Quien quiera rechazar duplicados explícitamente debe
    # comprobar slugify_display_name() antes (lo hace builder_service para la API).
    raw_config["name"] = sanitize_name(raw_config.get("display_name", ""), strategies_dir)

    raw_config["magic_number"] = generate_magic_number(strategies_dir)
    raw_config["schema_version"] = _requested_schema_version(raw_config)

    if _is_mtf_config(raw_config):
        from backend.strategy_builder.mtf_generator import validate_mtf_strategy_config
        validate_mtf_strategy_config(raw_config, is_new=True, strategies_dir=strategies_dir)
    else:
        validate_strategy_config(raw_config, is_new=True, strategies_dir=strategies_dir)
    return generate_strategy_file(raw_config, strategies_dir=strategies_dir)


def handle_save_edit(raw_config: dict, original_name: str, strategies_dir: Path = None) -> Path:
    """
    Full edit flow: preserve magic_number, handle rename, validate, generate, remove old files.
    Returns path to the written .py file.
    """
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    raw_config = dict(raw_config)
    stored_json_path = strategies_dir / f"strategy_{original_name}.json"
    if not stored_json_path.is_file():
        raise ValidationError(
            f"'{original_name}' no existe o no es una estrategia del Builder (falta strategy_{original_name}.json)."
        )
    stored_config = json.loads(stored_json_path.read_text(encoding="utf-8"))
    preserved_magic = stored_config.get("magic_number")
    if not isinstance(preserved_magic, int):
        raise ValidationError(
            f"strategy_{original_name}.json no tiene un magic_number válido; no se puede editar."
        )

    # sanitize_name(exclude_name=original_name) devuelve un nombre libre o el propio
    # original_name, por lo que un rename nunca colisiona.
    new_name = sanitize_name(raw_config.get("display_name", ""), strategies_dir,
                             exclude_name=original_name)
    raw_config["name"] = new_name
    raw_config["magic_number"] = preserved_magic
    raw_config["schema_version"] = _requested_schema_version(raw_config)

    if _is_mtf_config(raw_config):
        from backend.strategy_builder.mtf_generator import validate_mtf_strategy_config
        validate_mtf_strategy_config(raw_config, is_new=False, strategies_dir=strategies_dir)
    else:
        validate_strategy_config(raw_config, is_new=False, strategies_dir=strategies_dir)
    py_path = generate_strategy_file(raw_config, strategies_dir=strategies_dir)

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


def _requested_schema_version(config: dict) -> int:
    if str(config.get("mode") or "").strip().lower() in {"multi_timeframe", "mtf"}:
        return 2
    try:
        return int(config.get("schema_version") or 1)
    except (TypeError, ValueError):
        return 1


def _is_mtf_config(config: dict) -> bool:
    return _requested_schema_version(config) == 2


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

    # payload_extra_fields validation — these are interpolated into generated source,
    # so column references must resolve to a real column (no silent runtime failure / injection).
    _validate_payload_extra_fields(config.get("payload_extra_fields", []), available)

    # Identical buy/sell warning
    if (json.dumps(config["buy_condition"], sort_keys=True) ==
            json.dumps(config["sell_condition"], sort_keys=True)):
        logger.warning(
            "Buy and sell conditions are identical "
            "— strategy will always trade buy on conflict."
        )

    # VWAP on D1 warning
    has_vwap = any(ind["id"] == "VWAP" for ind in config["indicators"])
    if has_vwap and config["timeframe"] == "D1":
        logger.warning("VWAP is not meaningful on D1 timeframe.")


def _validate_payload_extra_fields(fields, available_columns: set) -> None:
    if not isinstance(fields, list):
        raise ValidationError("payload_extra_fields must be a list.")
    seen_keys: set = set()
    for i, field in enumerate(fields):
        path = f"payload_extra_fields[{i}]"
        if not isinstance(field, dict):
            raise ValidationError(f"{path}: must be an object.")
        key = field.get("key")
        if not isinstance(key, str) or not re.match(r'^[a-z_][a-z0-9_]*$', key):
            raise ValidationError(
                f"{path}: invalid key '{key}'. Use lowercase letters, digits, underscores."
            )
        if key in seen_keys:
            raise ValidationError(f"{path}: duplicate key '{key}'.")
        seen_keys.add(key)
        field_type = field.get("type")
        if field_type not in ("literal", "column"):
            raise ValidationError(
                f"{path}: type must be 'literal' or 'column' (got '{field_type}')."
            )
        if "value" not in field:
            raise ValidationError(f"{path}: missing 'value'.")
        if field_type == "column" and field["value"] not in available_columns:
            raise ValidationError(
                f"{path}: column '{field['value']}' not available. "
                f"Add the corresponding indicator."
            )


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


def generate_magic_number(strategies_dir: Path = None) -> int:
    """Return a random 5-digit magic number (10000–99999) not already in use.

    Scans strategy_*.json companions in strategies_dir to avoid collisions, so
    each generated strategy gets a unique magic for correct order attribution.
    """
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    used = _used_magic_numbers(strategies_dir)
    # 90000 possible values; with a sane number of strategies this terminates fast.
    if len(used) >= (99999 - 10000 + 1):
        raise GeneratorError("No free magic numbers available in range 10000–99999.")
    while True:
        magic = random.randint(10000, 99999)
        if magic not in used:
            return magic


def _used_magic_numbers(strategies_dir: Path) -> set:
    """Collect magic numbers already declared in strategy_*.json companions."""
    used: set = set()
    try:
        json_paths = strategies_dir.glob("strategy_*.json")
    except Exception:
        return used
    for json_path in json_paths:
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        magic = data.get("magic_number")
        if isinstance(magic, int):
            used.add(magic)
    return used


def slugify_display_name(display_name: str) -> str:
    """Base machine name derived from a display name (without collision suffixes)."""
    s = (display_name or "").lower()
    s = re.sub(r'[^a-z0-9_]', '_', s)
    s = re.sub(r'_+', '_', s)
    s = s.strip('_')
    if not s or s[0].isdigit():
        s = 'strategy_' + s
    return s


def sanitize_name(display_name: str, strategies_dir: Path = None, exclude_name: str = None) -> str:
    """
    Convert a user-visible display name to a valid machine name.
    Appends _2, _3, ... if the name is already taken (excluding exclude_name).
    """
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    base = slugify_display_name(display_name)
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
        spec = INDICATOR_SPECS[ind["id"]]
        for template in spec["constants"]:
            lines.append(ind_registry.format_template(template, ind["params"]))
    return "\n".join(lines)


def _emit_params_block(indicators: list) -> str:
    """Emit a PARAMS module-level dict for editable indicator parameters.

    Returns empty string if no non-pre-computed indicators have params.
    Nota: el bloque es declarativo (ver docstring del módulo) — los períodos van
    horneados en los nombres de columna.
    """
    entries = []
    for ind in indicators:
        if ind["pre_computed"]:
            continue
        spec = INDICATOR_SPECS[ind["id"]]
        for entry in spec["params_block"]:
            raw = ind["params"][entry["value_param"]]
            value = int(raw) if entry["type"] == "int" else float(raw)
            entries.append((
                ind_registry.format_template(entry["key"], ind["params"]),
                ind_registry.format_template(entry["label"], ind["params"]),
                entry["type"], value, entry["min"], entry["max"],
            ))

    if not entries:
        return ""

    lines = ["PARAMS = {"]
    for (key, label, type_str, default, min_val, max_val) in entries:
        lines.append(f'    "{key}": {{"label": "{label}", "type": "{type_str}", "default": {default!r}, "min": {min_val!r}, "max": {max_val!r}}},')
    lines.append("}")

    return "\n".join(lines)


def _overlay_series_specs(indicators: list) -> dict:
    trend_item = None
    band_item = None
    has_supertrend = False
    has_tci = False

    for ind in indicators:
        spec = INDICATOR_SPECS.get(ind["id"])
        overlay = spec["overlay"] if spec else None
        if not overlay:
            continue
        kind = overlay[0]
        if kind == "flag":
            if overlay[1] == "supertrend":
                has_supertrend = True
            elif overlay[1] == "tci":
                has_tci = True
            continue
        params = ind.get("params", {})
        item = {
            "label": ind_registry.format_template(overlay[1], params),
            "assignments": [
                (alias, ind_registry.format_template(col_tpl, params))
                for alias, col_tpl in overlay[2]
            ],
        }
        if kind == "trend":
            trend_item = item
        else:
            band_item = item

    return {
        "trend": trend_item,
        "bands": band_item,
        "supertrend": has_supertrend,
        "tci": has_tci,
    }


def _emit_strategy_object_tree_items(indicators: list) -> str:
    specs = _overlay_series_specs(indicators)
    entries = []

    if specs["trend"]:
        entries.append(
            f'{{"key": "baseline", "label": "{specs["trend"]["label"]}", "icon": "line", "toggle": True}}'
        )
    if specs["bands"]:
        entries.append(
            f'{{"key": "atr_bands", "label": "{specs["bands"]["label"]}", "icon": "bands", "toggle": True}}'
        )
    if specs["supertrend"]:
        entries.append('{"key": "supertrend", "label": "Supertrend", "icon": "trend", "toggle": True}')
    if specs["tci"]:
        entries.append('{"key": "tci", "label": "TCI", "icon": "hist", "toggle": True}')

    if not entries:
        return "OBJECT_TREE_ITEMS = []"

    return "OBJECT_TREE_ITEMS = [\n    " + ",\n    ".join(entries) + ",\n]"


def _emit_data_window_fields(indicators: list) -> str:
    entries = []
    for ind in indicators:
        spec = INDICATOR_SPECS.get(ind["id"])
        if spec is None:
            continue
        params = ind.get("params", {})
        for field in spec["data_window"]:
            key = ind_registry.format_template(field["key"], params)
            label = ind_registry.format_template(field["label"], params)
            entries.append(
                f'{{"key": "{key}", "label": "{label}", "format": "{field["format"]}", "section": "{field["section"]}"}}'
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


def _emit_helper_functions(indicators: list) -> str:
    custom = [ind for ind in indicators if not ind["pre_computed"]]
    return "\n\n".join(ind_registry.helpers_for(custom))


def _emit_indicator_computation_block(ind: dict) -> list:
    spec = INDICATOR_SPECS.get(ind["id"])
    if spec is None:
        raise ValueError(f"_emit_indicator_computation_block: unknown id '{ind['id']}'")
    return ind_registry.compute_lines(ind["id"], ind.get("params", {}))


def _emit_prepare_dataframe(
    indicators: list,
    custom_indicators: list,
    needs_close: bool,
    needs_high_low: bool,
    needs_volume: bool
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

    overlay_specs = _overlay_series_specs(indicators)
    trend_item = overlay_specs["trend"]
    if trend_item:
        for alias, source_col in trend_item["assignments"]:
            body.append(f'    if "{source_col}" in out.columns:')
            body.append(f'        out["{alias}"] = out["{source_col}"]')

    band_item = overlay_specs["bands"]
    if band_item:
        for alias, source_col in band_item["assignments"]:
            body.append(f'    if "{source_col}" in out.columns:')
            body.append(f'        out["{alias}"] = out["{source_col}"]')

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

    if extra_fields:
        extra_field_lines = ""
        for field in extra_fields:
            key = field["key"]
            if field["type"] == "literal":
                val = repr(field["value"])
            else:
                col = field["value"]
                val = f'df.iloc[-2]["{col}"]'
            extra_field_lines += f'            "{key}": {val},\n'

        return (
            f"def get_last_signal_payload(df: pd.DataFrame, verbose: bool = False) -> dict:\n"
            f"    signal = get_last_signal(df, verbose=verbose)\n"
            f"    reasons = {{\n"
            f'        "buy":  "{dn}: buy condition met",\n'
            f'        "sell": "{dn}: sell condition met",\n'
            f'        "none": "{dn}: no signal",\n'
            f"    }}\n"
            f'    if signal == "buy":\n'
            f"        return {{\n"
            f'            "signal": signal,\n'
            f'            "reason": reasons[signal],\n'
            f"{extra_field_lines}"
            f"        }}\n"
            f'    return {{"signal": signal, "reason": reasons[signal]}}'
        )

    return (
        f"def get_last_signal_payload(df: pd.DataFrame, verbose: bool = False) -> dict:\n"
        f"    signal = get_last_signal(df, verbose=verbose)\n"
        f"    reasons = {{\n"
        f'        "buy":  "{dn}: buy condition met",\n'
        f'        "sell": "{dn}: sell condition met",\n'
        f'        "none": "{dn}: no signal",\n'
        f"    }}\n"
        f'    return {{"signal": signal, "reason": reasons[signal]}}'
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
