"""Multi-timeframe Strategy Builder v2/v3 generator.

This module is intentionally separate from generator.py so schema_version=1
output remains stable and rollback can disable v2 without touching v1.

Esquema v2 (aditivo, configs antiguos siguen válidos):
- strategy_type "blocks": bloques con direction "long"|"short", tramos de riesgo,
  SL/TP en ATRs y piramidación (payload avanzado buy/sell).
- strategy_type "rules": buy_condition/sell_condition a nivel raíz con refs
  cualificadas "TF.columna" → señales buy/sell simples (SL/TP fijos de config).
- Indicadores: cualquiera del registry (backend/strategy_builder/indicators.py)
  declarado con su timeframe; los pre_computed no están disponibles en MTF.
"""

from __future__ import annotations

import ast
import copy
import json
import pprint
import re
from pathlib import Path

from backend.runtime.timeframes import TIMEFRAME_MINUTES, normalize_timeframe_label
from backend.strategy_builder import indicators as ind_registry
from backend.strategy_builder.generator import GeneratorError, STRATEGIES_DIR, ValidationError, _write_atomic
from backend.strategy_builder.indicators import INDICATOR_SPECS

VALID_MTF_INDICATOR_IDS = set(ind_registry.MTF_INDICATOR_IDS)
VALID_DIRECTIONS = {"long", "short"}

BASE_COLUMNS = {
    "open", "high", "low", "close", "tick_volume", "volume",
    "real_volume", "spread", "OHLC4", "HLC3", "HL2",
}


def generate_mtf_strategy_file(config: dict, strategies_dir: Path = None) -> Path:
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR
    py_content = render_mtf_strategy_source(config)
    name = config["name"]
    py_path = strategies_dir / f"strategy_{name}.py"
    json_path = strategies_dir / f"strategy_{name}.json"
    _write_atomic(py_path, py_content)
    _write_atomic(json_path, json.dumps(config, indent=2, ensure_ascii=False))
    return py_path


# ---------------------------------------------------------------------------
# Validación / normalización
# ---------------------------------------------------------------------------


def _strategy_type(config: dict) -> str:
    has_blocks = bool(config.get("blocks"))
    has_rules = bool(config.get("buy_condition") or config.get("sell_condition"))
    if has_blocks and has_rules:
        raise ValidationError(
            "Config MTF inválida: usa bloques O condiciones buy/sell a nivel raíz, no ambas."
        )
    if has_blocks:
        return "blocks"
    if has_rules:
        return "rules"
    raise ValidationError("Config MTF inválida: requiere 'blocks' o 'buy_condition'/'sell_condition'.")


def validate_mtf_strategy_config(config: dict, is_new: bool = True, strategies_dir: Path = None) -> None:
    if strategies_dir is None:
        strategies_dir = STRATEGIES_DIR

    required = {"schema_version", "name", "display_name", "magic_number"}
    missing = required - set(config.keys())
    if missing:
        raise ValidationError(f"Missing required fields: {sorted(missing)}")
    if int(config.get("schema_version") or 0) != 2:
        raise ValidationError(f"Unsupported MTF schema_version: {config.get('schema_version')!r}")

    name = str(config.get("name") or "")
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise ValidationError(f"Invalid strategy name '{name}'.")
    if not str(config.get("display_name") or "").strip():
        raise ValidationError("display_name is required.")

    magic = config.get("magic_number")
    if not isinstance(magic, int) or not (10000 <= magic <= 99999):
        raise ValidationError("magic_number must be an integer in range 10000-99999.")

    if is_new:
        py_path = strategies_dir / f"strategy_{name}.py"
        if py_path.exists():
            raise ValidationError(f"Strategy name '{name}' is already taken.")

    config["mode"] = "multi_timeframe"
    config["primary_timeframe"] = _valid_tf(config.get("primary_timeframe") or config.get("timeframe") or "M1")
    config["timeframe"] = config["primary_timeframe"]
    config["strategy_type"] = _strategy_type(config)
    primary = config["primary_timeframe"]

    config["indicators"] = _normalize_indicators(config.get("indicators") or [], default_tf=primary)

    if config["strategy_type"] == "blocks":
        config.pop("buy_condition", None)
        config.pop("sell_condition", None)
        config["blocks"] = _normalize_blocks(config)
        _ensure_block_indicators(config)
        config["indicators"] = _dedupe_indicators(config["indicators"])

        # Las refs sin timeframe se evalúan en runtime sobre el timeframe primario
        # (template _parse_ref); se cualifican aquí para que la config almacenada sea
        # explícita y la validación coincida con el runtime.
        for block in config["blocks"]:
            block["entry_condition"] = _qualify_condition_refs(block["entry_condition"], primary)
            block["direction_condition"] = _qualify_condition_refs(block["direction_condition"], primary)
            block["atr_ref"] = _qualify_ref(block["atr_ref"], primary)
            block["tiers"] = [
                {**tier, "condition": _qualify_condition_refs(tier["condition"], primary)}
                for tier in block["tiers"]
            ]

        config["frames"] = _normalize_frames(config)
        available = _available_columns(config)
        for block in config["blocks"]:
            _validate_condition(block["entry_condition"], available, f"blocks[{block['id']}].entry_condition", primary)
            _validate_condition(block["direction_condition"], available, f"blocks[{block['id']}].direction_condition", primary)
            _validate_ref(block["atr_ref"], available, f"blocks[{block['id']}].atr_ref", primary)
            for i, tier in enumerate(block["tiers"]):
                _validate_condition(tier["condition"], available, f"blocks[{block['id']}].tiers[{i}].condition", primary)
        _validate_parent_graph(config["blocks"])
    else:
        config["blocks"] = []
        if not config.get("buy_condition") or not config.get("sell_condition"):
            raise ValidationError("Modo reglas MTF: se requieren buy_condition y sell_condition.")
        config["buy_condition"] = _qualify_condition_refs(config["buy_condition"], primary)
        config["sell_condition"] = _qualify_condition_refs(config["sell_condition"], primary)
        config["indicators"] = _dedupe_indicators(config["indicators"])
        config["frames"] = _normalize_frames(config)
        available = _available_columns(config)
        _validate_condition(config["buy_condition"], available, "buy_condition", primary)
        _validate_condition(config["sell_condition"], available, "sell_condition", primary)


def _valid_tf(value) -> str:
    label = normalize_timeframe_label(value)
    if not label:
        raise ValidationError(f"Invalid timeframe '{value}'. Must be one of {sorted(TIMEFRAME_MINUTES)}.")
    return label


def _normalize_frames(config: dict) -> list[dict]:
    seen = set(_collect_timeframes(config))
    for frame in config.get("frames") or []:
        if isinstance(frame, dict):
            seen.add(_valid_tf(frame.get("timeframe") or frame.get("id")))
        else:
            seen.add(_valid_tf(frame))
    return [{"id": tf, "timeframe": tf} for tf in sorted(seen, key=lambda tf: TIMEFRAME_MINUTES[tf])]


def _indicator_columns(ind_id: str, period: int) -> list[str]:
    # Compat: firma histórica (period); el camino general usa el registry con params.
    if ind_id not in VALID_MTF_INDICATOR_IDS:
        raise ValidationError(f"Unknown MTF indicator id '{ind_id}'.")
    return ind_registry.indicator_columns(ind_id, {"period": period})


def _normalize_indicators(indicators: list, default_tf: str) -> list[dict]:
    normalized = []
    for i, raw in enumerate(indicators):
        if not isinstance(raw, dict):
            raise ValidationError(f"indicators[{i}] must be an object.")
        ind_id = str(raw.get("id") or "").upper()
        if ind_id not in VALID_MTF_INDICATOR_IDS:
            raise ValidationError(
                f"Unknown MTF indicator id '{ind_id}'. "
                f"Los indicadores pre-calculados del gráfico no están disponibles en MTF."
            )
        spec = INDICATOR_SPECS[ind_id]
        raw_params = raw.get("params") or {}
        params = {}
        for p in spec["params"]:
            value = raw_params.get(p["key"], p["default"])
            try:
                params[p["key"]] = int(value) if p["type"] == "int" else float(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"indicators[{i}].params.{p['key']} must be numeric.") from exc
        tf = _valid_tf(raw.get("timeframe") or raw.get("frame") or default_tf)
        normalized.append({
            "id": ind_id,
            "timeframe": tf,
            "params": params,
            "columns": ind_registry.indicator_columns(ind_id, params),
            "pre_computed": False,
        })
    return normalized


def _normalize_blocks(config: dict) -> list[dict]:
    blocks = config.get("blocks") or []
    if not isinstance(blocks, list) or not blocks:
        raise ValidationError("MTF config requires at least one block.")
    normalized = []
    for i, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            raise ValidationError(f"blocks[{i}] must be an object.")
        block_id = str(raw.get("id") or raw.get("name") or f"block_{i + 1}").strip()
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", block_id):
            raise ValidationError(f"Invalid block id '{block_id}'.")
        direction = str(raw.get("direction") or "long").strip().lower()
        if direction not in VALID_DIRECTIONS:
            raise ValidationError(f"blocks[{i}].direction must be 'long' or 'short' (got '{direction}').")
        trigger_tf = _valid_tf(raw.get("trigger_timeframe") or config["primary_timeframe"])
        confirm_raw = raw.get("confirm_timeframes") or []
        if not isinstance(confirm_raw, list):
            raise ValidationError(f"blocks[{i}].confirm_timeframes must be a list.")
        confirm_tfs = [_valid_tf(tf) for tf in confirm_raw]
        vortex_period = int(raw.get("vortex_period") or 14)
        atr_period = int(raw.get("atr_period") or 14)
        risk_tiers = raw.get("risk_tiers") or [0.01]
        if not isinstance(risk_tiers, list) or not risk_tiers:
            raise ValidationError(f"blocks[{i}].risk_tiers must be a non-empty list.")
        try:
            risk_tiers = [float(risk_pct) for risk_pct in risk_tiers]
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"blocks[{i}].risk_tiers must contain numeric values.") from exc
        if any(risk_pct < 0 for risk_pct in risk_tiers):
            raise ValidationError(f"blocks[{i}].risk_tiers cannot contain negative values.")
        parent_block = raw.get("parent_block")
        if parent_block is None and isinstance(raw.get("direction_filter"), dict):
            parent_block = raw["direction_filter"].get("block")

        # Defaults Vortex espejados por dirección.
        if direction == "long":
            default_entry = _condition(f"{trigger_tf}.vortex_cross_up_{vortex_period}", ">", 0)
            default_dir = _condition(f"{trigger_tf}.vortex_dir_{vortex_period}", "==", 1)
            dir_value = 1
        else:
            default_entry = _condition(f"{trigger_tf}.vortex_cross_down_{vortex_period}", ">", 0)
            default_dir = _condition(f"{trigger_tf}.vortex_dir_{vortex_period}", "==", -1)
            dir_value = -1

        entry_condition = raw.get("entry_condition") or default_entry
        direction_condition = raw.get("direction_condition") or default_dir

        tiers = raw.get("tiers")
        if not tiers:
            tiers = []
            tier_timeframes = [trigger_tf] + confirm_tfs
            for tier_index, risk_pct in enumerate(risk_tiers):
                tf = tier_timeframes[min(tier_index, len(tier_timeframes) - 1)]
                condition = entry_condition if tier_index == 0 else _condition(
                    f"{tf}.vortex_dir_{vortex_period}", "==", dir_value
                )
                tiers.append({
                    "id": f"tier{tier_index + 1}",
                    "entry_index": tier_index,
                    "risk_pct": float(risk_pct),
                    "condition": condition,
                })
        else:
            tiers = [_normalize_tier(tier, j) for j, tier in enumerate(tiers)]

        normalized.append({
            "id": block_id,
            "direction": direction,
            "trigger_timeframe": trigger_tf,
            "confirm_timeframes": confirm_tfs,
            "parent_block": str(parent_block).strip() if parent_block else None,
            "entry_condition": entry_condition,
            "direction_condition": direction_condition,
            "atr_ref": raw.get("atr_ref") or {"timeframe": trigger_tf, "column": f"atr_{atr_period}", "shift": 2},
            "atr_period": atr_period,
            "vortex_period": vortex_period,
            "sl_atr_mult": float(raw.get("sl_atr_mult", raw.get("atr_sl_mult", 1.5))),
            "tp_rr": float(raw.get("tp_rr", raw.get("tp_ratio", 2.0))),
            "pyramid_atr_mult": float(raw.get("pyramid_atr_mult", 0.5)),
            "max_entries": int(raw.get("max_entries") or len(tiers)),
            "tiers": tiers,
        })
    return normalized


def _normalize_tier(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError(f"tier[{index}] must be an object.")
    try:
        risk_pct = float(raw.get("risk_pct") or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"tier[{index}].risk_pct must be numeric.") from exc
    if risk_pct < 0:
        raise ValidationError(f"tier[{index}].risk_pct cannot be negative.")
    return {
        "id": str(raw.get("id") or f"tier{index + 1}"),
        "entry_index": int(raw.get("entry_index", index)),
        "risk_pct": risk_pct,
        "condition": raw.get("condition"),
    }


def _condition(left, op, right) -> dict:
    return {"type": "condition", "left": left, "op": op, "right": right}


def _dedupe_indicators(indicators: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for ind in indicators:
        key = (ind["id"], ind["timeframe"], json.dumps(ind["params"], sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        out.append(ind)
    return out


def _ensure_block_indicators(config: dict) -> None:
    indicators = list(config["indicators"])
    for block in config["blocks"]:
        indicators.append(_make_indicator("ATR", block["trigger_timeframe"], block["atr_period"]))
        indicators.append(_make_indicator("VORTEX", block["trigger_timeframe"], block["vortex_period"]))
        for tf in block["confirm_timeframes"]:
            indicators.append(_make_indicator("VORTEX", tf, block["vortex_period"]))
    config["indicators"] = indicators


def _make_indicator(ind_id: str, timeframe: str, period: int) -> dict:
    params = {"period": int(period)}
    return {
        "id": ind_id,
        "timeframe": timeframe,
        "params": params,
        "columns": ind_registry.indicator_columns(ind_id, params),
        "pre_computed": False,
    }


def _collect_condition_timeframes(node, default_tf: str) -> set[str]:
    out: set[str] = set()
    if not isinstance(node, dict):
        return out
    if str(node.get("type") or "").upper() == "CONDITION":
        for ref in (node.get("left"), node.get("right")):
            if isinstance(ref, str) and "." in ref:
                out.add(_valid_tf(ref.split(".", 1)[0]))
            elif isinstance(ref, dict):
                out.add(_valid_tf(ref.get("timeframe") or ref.get("frame") or default_tf))
        return out
    for child in node.get("children") or []:
        out |= _collect_condition_timeframes(child, default_tf)
    return out


def _collect_timeframes(config: dict) -> set[str]:
    primary = config["primary_timeframe"]
    labels = {primary}
    for frame in config.get("frames") or []:
        labels.add(_valid_tf(frame.get("timeframe") if isinstance(frame, dict) else frame))
    for ind in config.get("indicators") or []:
        labels.add(_valid_tf(ind.get("timeframe")))
    for block in config.get("blocks") or []:
        labels.add(_valid_tf(block["trigger_timeframe"]))
        for tf in block.get("confirm_timeframes") or []:
            labels.add(_valid_tf(tf))
        for node in (block.get("entry_condition"), block.get("direction_condition")):
            labels |= _collect_condition_timeframes(node, primary)
        for tier in block.get("tiers") or []:
            labels |= _collect_condition_timeframes(tier.get("condition"), primary)
    for node in (config.get("buy_condition"), config.get("sell_condition")):
        if node:
            labels |= _collect_condition_timeframes(node, primary)
    return labels


def _available_columns(config: dict) -> dict[str, set[str]]:
    available = {tf: set(BASE_COLUMNS) for tf in _collect_timeframes(config)}
    for ind in config["indicators"]:
        available.setdefault(ind["timeframe"], set(BASE_COLUMNS)).update(ind["columns"])
    return available


def _qualify_ref(ref, default_tf: str):
    """Devuelve la referencia con timeframe explícito (default: el primario)."""
    if ref is None or isinstance(ref, (int, float, bool)):
        return ref
    if isinstance(ref, str):
        return ref if "." in ref else f"{default_tf}.{ref}"
    if isinstance(ref, dict):
        out = dict(ref)
        out["timeframe"] = out.get("timeframe") or out.get("frame") or default_tf
        out.pop("frame", None)
        return out
    return ref


def _qualify_condition_refs(node, default_tf: str):
    if not isinstance(node, dict):
        return node
    node_type = str(node.get("type") or "").upper()
    if node_type == "CONDITION":
        out = dict(node)
        out["left"] = _qualify_ref(node.get("left"), default_tf)
        out["right"] = _qualify_ref(node.get("right"), default_tf)
        return out
    out = dict(node)
    out["children"] = [_qualify_condition_refs(child, default_tf) for child in node.get("children") or []]
    return out


def _validate_ref(ref, available: dict[str, set[str]], path: str, default_tf: str = "M1") -> None:
    if isinstance(ref, (int, float, bool)):
        return
    if isinstance(ref, str):
        if "." in ref:
            tf, col = ref.split(".", 1)
        else:
            tf, col = default_tf, ref
    elif isinstance(ref, dict):
        tf = ref.get("timeframe") or ref.get("frame") or default_tf
        col = ref.get("column")
    else:
        raise ValidationError(f"{path}: invalid reference {ref!r}")
    tf = _valid_tf(tf)
    if col not in available.get(tf, set()):
        raise ValidationError(f"{path}: column '{tf}.{col}' is not available.")


def _validate_condition(node, available: dict[str, set[str]], path: str, default_tf: str = "M1") -> None:
    if not isinstance(node, dict):
        raise ValidationError(f"{path}: condition must be an object.")
    node_type = str(node.get("type") or "").upper()
    if node_type == "CONDITION":
        if node.get("op") not in {"<", ">", "<=", ">=", "==", "!="}:
            raise ValidationError(f"{path}: invalid operator '{node.get('op')}'.")
        _validate_ref(node.get("left"), available, f"{path}.left", default_tf)
        _validate_ref(node.get("right"), available, f"{path}.right", default_tf)
        return
    if node_type in {"AND", "OR"}:
        children = node.get("children") or []
        if len(children) < 1:
            raise ValidationError(f"{path}: group must have children.")
        for i, child in enumerate(children):
            _validate_condition(child, available, f"{path}.children[{i}]", default_tf)
        return
    raise ValidationError(f"{path}: unknown node type '{node.get('type')}'.")


def _validate_parent_graph(blocks: list[dict]) -> None:
    ids = {block["id"] for block in blocks}
    parents = {block["id"]: block.get("parent_block") for block in blocks if block.get("parent_block")}
    for block_id, parent_id in parents.items():
        if parent_id not in ids:
            raise ValidationError(f"Block '{block_id}' references unknown parent block '{parent_id}'.")
    for block_id in ids:
        seen = set()
        current = block_id
        while current in parents:
            current = parents[current]
            if current in seen:
                raise ValidationError(f"Cycle detected in block direction filters at '{block_id}'.")
            seen.add(current)


# ---------------------------------------------------------------------------
# Codegen
# ---------------------------------------------------------------------------

_RUNTIME_EVAL_TEMPLATE = '''\
def _parse_ref(ref):
    if isinstance(ref, dict):
        return ref.get("timeframe") or ref.get("frame") or TIMEFRAME, ref.get("column"), int(ref.get("shift") or 2)
    if isinstance(ref, str):
        if "." in ref:
            timeframe, column = ref.split(".", 1)
        else:
            timeframe, column = TIMEFRAME, ref
        return timeframe, column, 2
    return None, None, 2


def _get_value(ref, frames):
    if isinstance(ref, (int, float, bool)):
        return ref
    timeframe, column, shift = _parse_ref(ref)
    if not timeframe or not column:
        return None
    df = frames.get(timeframe)
    if not isinstance(df, pd.DataFrame) or column not in df.columns or len(df) < shift:
        return None
    value = df.iloc[-shift][column]
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return value


def _compare(left, op, right) -> bool:
    if left is None or right is None:
        return False
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    return False


def _eval_condition_tree(node, frames) -> bool:
    if not isinstance(node, dict):
        return False
    node_type = str(node.get("type") or "").upper()
    if node_type == "CONDITION":
        return _compare(_get_value(node.get("left"), frames), node.get("op"), _get_value(node.get("right"), frames))
    children = node.get("children") or []
    if node_type == "AND":
        return all(_eval_condition_tree(child, frames) for child in children)
    if node_type == "OR":
        return any(_eval_condition_tree(child, frames) for child in children)
    return False'''

_FRAMES_TEMPLATE = '''\
def prepare_frames(frames: dict) -> dict:
    out = {}
    for timeframe in REQUIRED_TIMEFRAMES:
        df = frames.get(timeframe)
        if isinstance(df, pd.DataFrame):
            out[timeframe] = _prepare_frame(df, timeframe)
    return out


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    return prepare_frames({TIMEFRAME: df}).get(TIMEFRAME, df)'''

_BLOCKS_PAYLOAD_TEMPLATE = '''\
def _block_by_id(block_id: str):
    for block in MTF_CONFIG.get("blocks", []):
        if block.get("id") == block_id:
            return block
    return None


def _block_direction_active(block, frames) -> bool:
    return _eval_condition_tree(block.get("direction_condition"), frames)


def _parent_allows(block, frames) -> bool:
    parent_id = block.get("parent_block")
    if not parent_id:
        return True
    parent = _block_by_id(parent_id)
    return bool(parent and _block_direction_active(parent, frames))


def get_last_signal_payload_mtf(frames: dict, verbose: bool = False, params=None) -> dict:
    prepared = prepare_frames(frames or {})
    for block in MTF_CONFIG.get("blocks", []):
        if not _parent_allows(block, prepared):
            continue
        signal = "sell" if block.get("direction") == "short" else "buy"
        tiers = block.get("tiers") or []
        for tier in tiers:
            if not _eval_condition_tree(tier.get("condition"), prepared):
                continue
            atr_value = _get_value(block.get("atr_ref"), prepared)
            try:
                atr_value = float(atr_value or 0.0)
            except (TypeError, ValueError):
                atr_value = 0.0
            if atr_value <= 0:
                continue
            sl_atr_mult = float(block.get("sl_atr_mult") or 1.0)
            tp_rr = float(block.get("tp_rr") or 2.0)
            return {
                "signal": signal,
                "reason": f"{block.get('id')}/{tier.get('id')} MTF condition met",
                "pyramiding": True,
                "atr_value": atr_value,
                "sl_atr_mult": sl_atr_mult,
                "tp_atr_mult": sl_atr_mult * tp_rr,
                "pyramid_atr_mult": float(block.get("pyramid_atr_mult") or 0.5),
                "risk_pct": float(tier.get("risk_pct") or 0.0),
                "entry_index": int(tier.get("entry_index") or 0),
                "max_entries": int(block.get("max_entries") or len(tiers) or 1),
                "block_id": str(block.get("id") or ""),
                "tier_id": str(tier.get("id") or ""),
            }
    return {"signal": "none", "reason": "MTF: no block signal"}'''

_RULES_PAYLOAD_TEMPLATE = '''\
def get_last_signal_payload_mtf(frames: dict, verbose: bool = False, params=None) -> dict:
    prepared = prepare_frames(frames or {})
    if _eval_condition_tree(MTF_CONFIG.get("buy_condition"), prepared):
        return {"signal": "buy", "reason": f"{DISPLAY_NAME}: buy condition met"}
    if _eval_condition_tree(MTF_CONFIG.get("sell_condition"), prepared):
        return {"signal": "sell", "reason": f"{DISPLAY_NAME}: sell condition met"}
    return {"signal": "none", "reason": f"{DISPLAY_NAME}: no signal"}'''

_TAIL_TEMPLATE = '''\
def get_last_signal_payload(df: pd.DataFrame, verbose: bool = False, params=None) -> dict:
    return get_last_signal_payload_mtf({TIMEFRAME: df}, verbose=verbose, params=params)


def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    return get_last_signal_payload(df, verbose=verbose).get("signal", "none")'''


def _emit_prepare_frame(config: dict) -> str:
    """Genera _prepare_frame con un branch por timeframe que computa sus indicadores."""
    by_tf: dict[str, list[dict]] = {}
    for ind in config["indicators"]:
        by_tf.setdefault(ind["timeframe"], []).append(ind)

    needs_volume = "volume" in ind_registry.needed_series(config["indicators"])

    lines = [
        "def _prepare_frame(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:",
        "    out = df.copy()",
        '    if not {"high", "low", "close"}.issubset(out.columns):',
        "        return out",
        '    close = _numeric(out, "close")',
        '    high  = _numeric(out, "high")',
        '    low   = _numeric(out, "low")',
    ]
    if needs_volume:
        lines.append("    volume = _volume_series(out)")
    lines += [
        '    out["OHLC4"] = (_numeric(out, "open") + high + low + close) / 4.0',
        '    out["HLC3"]  = (high + low + close) / 3.0',
        '    out["HL2"]   = (high + low) / 2.0',
    ]
    for tf in sorted(by_tf, key=lambda t: TIMEFRAME_MINUTES[t]):
        lines.append(f'    if timeframe == "{tf}":')
        for ind in by_tf[tf]:
            for compute_line in ind_registry.compute_lines(ind["id"], ind["params"]):
                lines.append("    " + compute_line)
            for col in ind["columns"]:
                lines.append(f'        out["{col}"] = {col}')
    lines.append("    return out")
    return "\n".join(lines)


def render_mtf_strategy_source(config: dict) -> str:
    render_config = copy.deepcopy(config)
    validate_mtf_strategy_config(render_config, is_new=False, strategies_dir=Path("__builder_render__"))
    config_repr = pprint.pformat(render_config, width=100, sort_dicts=False)
    required = sorted(_collect_timeframes(render_config), key=lambda tf: TIMEFRAME_MINUTES[tf])
    display_name = str(render_config["display_name"]).replace('"', '\\"')

    header = (
        '"""\n'
        "Generated by Strategy Builder v2 (multi-timeframe).\n"
        '"""\n\n'
        "import pandas as pd\n\n"
        "SCHEMA_VERSION = 2\n"
        'MODE = "multi_timeframe"\n'
        f'STRATEGY_TYPE = "{render_config["strategy_type"]}"\n'
        f'DISPLAY_NAME = "{display_name}"\n'
        f'TIMEFRAME = "{render_config["primary_timeframe"]}"\n'
        "PRIMARY_TIMEFRAME = TIMEFRAME\n"
        f"REQUIRED_TIMEFRAMES = {required!r}\n"
        f"MAGIC_NUMBER = {int(render_config['magic_number'])}\n"
        "PARAMS = {}\n"
        "OBJECT_TREE_ITEMS = []\n"
        "DATA_WINDOW_FIELDS = []\n"
        f"MTF_CONFIG = {config_repr}"
    )

    helpers = "\n\n".join(ind_registry.helpers_for(render_config["indicators"]))
    payload = _BLOCKS_PAYLOAD_TEMPLATE if render_config["strategy_type"] == "blocks" else _RULES_PAYLOAD_TEMPLATE

    sections = [
        header,
        helpers,
        _emit_prepare_frame(render_config),
        _FRAMES_TEMPLATE,
        _RUNTIME_EVAL_TEMPLATE,
        payload,
        _TAIL_TEMPLATE,
    ]
    source = "\n\n\n".join(sections) + "\n"

    try:
        ast.parse(source)
    except SyntaxError as exc:
        raise GeneratorError(f"Generated MTF code failed ast.parse: {exc}") from exc
    return source
