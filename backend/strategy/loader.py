# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
backend/strategy/loader.py — Descubrimiento y carga de estrategias activas.

Resuelve módulos de estrategia (por clave, ruta o convención strategies.strategy_<key>),
valida su esquema PARAMS, aplica overrides .params.json y asigna magic numbers por
estrategia. Broker-agnóstico: los timeframes se resuelven vía backend.strategy.runtime.
"""

import importlib
import importlib.util
import inspect
import json
import os
import re
import zlib

from backend.core import config
from backend.strategy.runtime import (
    TIMEFRAME_MAP,
    get_strategy_timeframe,
    lowest_timeframe_label,
    module_required_timeframes,
    resolve_timeframe_value,
    timeframe_label,
)

# Raíz del repo (este módulo vive en backend/strategy/; las estrategias en <raíz>/strategies).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_v1_module(module) -> bool:
    return (
        getattr(module, "STRATEGY_API_VERSION", None) == 1
        and hasattr(module, "decide")
    )


def _slugify(text: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", (text or "").strip().lower()).strip("_")
    return value or "strategy"


def _looks_like_path(module_ref: str) -> bool:
    module_ref = module_ref or ""
    return module_ref.endswith(".py") or any(sep in module_ref for sep in (os.sep, os.altsep) if sep)


def _strategy_module_stem(module_ref: str) -> str:
    module_ref = (module_ref or "").strip()
    if not module_ref:
        return ""
    if _looks_like_path(module_ref):
        return os.path.splitext(os.path.basename(module_ref))[0].strip().lower()
    return module_ref.split(".")[-1].strip().lower()


def _load_strategy_module(module_ref: str):
    module_ref = (module_ref or "").strip()
    if not module_ref:
        raise ValueError("Referencia de modulo vacia")

    if _looks_like_path(module_ref):
        path = module_ref
        if not os.path.isabs(path):
            path = os.path.join(_PROJECT_ROOT, path)
        if not path.lower().endswith(".py"):
            candidate = f"{path}.py"
            if os.path.isfile(candidate):
                path = candidate
        if not os.path.isfile(path):
            raise FileNotFoundError(f"No se encontro estrategia: {path}")

        module_name = f"user_strategy_{_slugify(os.path.splitext(os.path.basename(path))[0])}_{zlib.crc32(path.encode('utf-8')):08x}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"No se pudo crear spec para {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    importlib.invalidate_caches()
    return importlib.reload(importlib.import_module(module_ref))


def _discover_strategy_modules_from_dir() -> dict:
    strategy_dir = getattr(config, "STRATEGY_DIR", "strategies")
    if not os.path.isabs(strategy_dir):
        strategy_dir = os.path.join(_PROJECT_ROOT, strategy_dir)
    if not os.path.isdir(strategy_dir):
        return {}

    project_root = _PROJECT_ROOT
    discovered = {}
    for filename in sorted(os.listdir(strategy_dir), key=str.lower):
        if not filename.lower().endswith(".py"):
            continue
        stem = os.path.splitext(filename)[0]
        if not stem or stem.startswith("__"):
            continue
        abs_path = os.path.join(strategy_dir, filename)
        rel_path = os.path.relpath(abs_path, project_root)
        keys = [_slugify(stem)]
        if stem.lower().startswith("strategy_"):
            keys.append(_slugify(stem[len("strategy_"):]))
        for key in keys:
            discovered.setdefault(key, rel_path)
    return discovered


def _candidate_module_refs(key: str, explicit_module_ref: str, default_key: str, default_module_ref: str, discovered_map: dict):
    refs = []
    if explicit_module_ref:
        refs.append(explicit_module_ref)
    if key == default_key and default_module_ref:
        refs.append(default_module_ref)
    if key in discovered_map:
        refs.append(discovered_map[key])
    refs.extend([f"strategies.{key}", f"strategies.strategy_{key}"])

    unique = []
    seen = set()
    for ref in refs:
        cleaned = (ref or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)
    return unique


def _resolve_strategy_magic_number(key: str, module, multi_mode: bool, magic_override=None) -> int:
    if isinstance(magic_override, int) and magic_override > 0:
        return int(magic_override)
    module_magic = getattr(module, "MAGIC_NUMBER", None) if module is not None else None
    if isinstance(module_magic, int) and module_magic > 0:
        return int(module_magic)

    base_magic = int(getattr(config, "MAGIC_NUMBER", 1) or 1)
    if not multi_mode:
        return base_magic

    offset = (zlib.crc32((key or "").encode("utf-8")) % 997) + 1
    candidate = base_magic * 1000 + offset
    if candidate > 2147483646:
        candidate = base_magic + offset
    return int(candidate)


def _validate_params_schema(raw_params) -> dict:
    """Validates a PARAMS module attribute. Returns a validated dict or None."""
    if raw_params is None:
        return None

    if not isinstance(raw_params, dict):
        return None

    validated = {}
    for key, entry in raw_params.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(entry, dict):
            continue

        type_str = entry.get("type")
        if type_str not in ("int", "float"):
            continue

        default = entry.get("default")
        min_val = entry.get("min")
        max_val = entry.get("max")
        label = entry.get("label", key)

        try:
            if type_str == "int":
                default = int(default)
                min_val = int(min_val)
                max_val = int(max_val)
            else:
                default = float(default)
                min_val = float(min_val)
                max_val = float(max_val)
        except (TypeError, ValueError):
            continue

        if not (min_val <= default <= max_val):
            continue

        validated[key] = {
            "label": str(label),
            "type": type_str,
            "default": default,
            "min": min_val,
            "max": max_val,
        }

    return validated


def _load_strategy_params(module, strategy_key: str, strategies_dir: str) -> dict:
    """Merges PARAMS schema defaults with .params.json overrides. Returns {key: value}."""
    raw_params = getattr(module, "PARAMS", None)
    schema = _validate_params_schema(raw_params)

    if schema is None or len(schema) == 0:
        return {}

    merged = {key: entry["default"] for key, entry in schema.items()}

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
                        continue
                    type_str = schema[key]["type"]
                    min_val = schema[key]["min"]
                    max_val = schema[key]["max"]
                    try:
                        if type_str == "int":
                            coerced = int(value)
                        else:
                            coerced = float(value)
                    except (TypeError, ValueError):
                        continue
                    coerced = max(min_val, min(max_val, coerced))
                    merged[key] = coerced
        except (OSError, json.JSONDecodeError):
            pass

    return merged


def _detect_params_kwarg(module) -> bool:
    """Returns True if the strategy's signal function accepts a 'params' keyword argument."""
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
        for p in params_in_sig.values():
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                return True
        return False

    return False


def load_active_strategies():
    raw_default_key = str(getattr(config, "STRATEGY_KEY", "") or "").strip()
    default_key = _slugify(raw_default_key) if raw_default_key else ""
    default_module_ref = str(getattr(config, "STRATEGY_MODULE", "") or "").strip()
    if default_key and not default_module_ref:
        default_module_ref = f"strategies.strategy_{default_key}"

    strategy_dir_raw = getattr(config, "STRATEGY_DIR", "strategies")
    if not os.path.isabs(strategy_dir_raw):
        strategies_dir = os.path.join(_PROJECT_ROOT, strategy_dir_raw)
    else:
        strategies_dir = strategy_dir_raw

    active_raw = getattr(config, "ACTIVE_STRATEGIES", None)
    discovered_map = _discover_strategy_modules_from_dir()
    if isinstance(active_raw, (list, tuple, set)) and active_raw:
        requested = list(active_raw)
    elif default_key:
        requested = [default_key]
    elif discovered_map:
        requested = [next(iter(discovered_map.keys()))]
    else:
        requested = []

    entries = []
    used_keys = set()

    for index, item in enumerate(requested):
        entry_dict = item if isinstance(item, dict) else {}
        explicit_module_ref = ""
        raw_key = ""
        label = ""

        if isinstance(item, dict):
            raw_key = str(entry_dict.get("key") or entry_dict.get("label") or entry_dict.get("module") or "").strip()
            explicit_module_ref = str(entry_dict.get("module") or entry_dict.get("module_ref") or entry_dict.get("path") or "").strip()
            label = str(entry_dict.get("label") or raw_key or f"strategy_{index + 1}")
        else:
            raw_value = str(item or "").strip()
            if not raw_value:
                continue
            label = raw_value
            if _looks_like_path(raw_value) or "." in raw_value:
                explicit_module_ref = raw_value
                raw_key = _strategy_module_stem(raw_value)
            else:
                raw_key = raw_value

        key = _slugify(raw_key or f"strategy_{index + 1}")
        base_key = key
        suffix = 2
        while key in used_keys:
            key = f"{base_key}_{suffix}"
            suffix += 1
        used_keys.add(key)

        module = None
        module_ref = ""
        last_error = ""
        for candidate in _candidate_module_refs(key, explicit_module_ref, default_key, default_module_ref, discovered_map):
            try:
                module = _load_strategy_module(candidate)
                module_ref = candidate
                break
            except Exception as error:
                last_error = str(error)

        if module is None:
            print(f"[loader] Estrategia '{key}' descartada: no se pudo cargar ({last_error or 'sin detalle'})")
            continue

        _is_legacy = hasattr(module, "get_last_signal") or hasattr(module, "get_last_signal_payload")
        _is_v1 = is_v1_module(module)
        _mode = getattr(config, "STRATEGY_RUNTIME_MODE", "legacy")
        if _mode == "v1_only" and not _is_v1:
            continue  # En modo v1_only solo se admiten módulos con decide() + STRATEGY_API_VERSION=1
        if not _is_legacy and not _is_v1:
            continue

        raw_timeframe = entry_dict.get("timeframe") if isinstance(item, dict) else None
        if raw_timeframe is None:
            raw_timeframe = get_strategy_timeframe(module)
        timeframe_value = resolve_timeframe_value(raw_timeframe)
        if timeframe_value is None:
            timeframe_value = resolve_timeframe_value(getattr(config, "TIMEFRAME", None)) or TIMEFRAME_MAP["M1"]

        raw_params = getattr(module, "PARAMS", None)
        params_schema = _validate_params_schema(raw_params)
        params_values = _load_strategy_params(module, key, strategies_dir)
        accepts_params = _detect_params_kwarg(module)

        entries.append(
            {
                "key": key,
                "label": label or key,
                "module_ref": module_ref,
                "module": module,
                "timeframe_value": timeframe_value,
                "timeframe_label": timeframe_label(timeframe_value) or "M1",
                "magic_override": entry_dict.get("magic_number") if isinstance(item, dict) else None,
                "params_schema": params_schema,
                "params_values": params_values,
                "accepts_params": accepts_params,
            }
        )

    if not entries:
        fallback_key = default_key
        if discovered_map:
            fallback_key = next(iter(discovered_map.keys()), fallback_key)
        if not fallback_key:
            raise RuntimeError("No hay estrategias válidas disponibles en la carpeta configurada.")
        module_ref = ""
        module = None
        last_error = ""
        for candidate in _candidate_module_refs(
            key=fallback_key,
            explicit_module_ref="",
            default_key=default_key,
            default_module_ref=default_module_ref,
            discovered_map=discovered_map,
        ):
            try:
                module = _load_strategy_module(candidate)
                module_ref = candidate
                break
            except Exception as error:
                last_error = str(error)
        if module is None:
            raise RuntimeError(
                f"No hay estrategias validas y fallo fallback por convención a '{fallback_key}': {last_error or 'sin detalle'}"
            )
        raw_params_fb = getattr(module, "PARAMS", None)
        params_schema_fb = _validate_params_schema(raw_params_fb)
        params_values_fb = _load_strategy_params(module, fallback_key, strategies_dir)
        accepts_params_fb = _detect_params_kwarg(module)

        entries = [
            {
                "key": fallback_key,
                "label": fallback_key,
                "module_ref": module_ref,
                "module": module,
                "timeframe_value": TIMEFRAME_MAP["M1"],
                "timeframe_label": "M1",
                "magic_override": None,
                "params_schema": params_schema_fb,
                "params_values": params_values_fb,
                "accepts_params": accepts_params_fb,
            }
        ]
    multi_mode = len(entries) > 1
    for entry in entries:
        entry["magic_number"] = _resolve_strategy_magic_number(
            key=entry["key"],
            module=entry["module"],
            multi_mode=multi_mode,
            magic_override=entry.get("magic_override"),
        )
        # Timeframes requeridos (MTF): el scheduling y la descarga de mercado usan
        # el menor; timeframe_label sigue siendo el primario de la estrategia.
        required = module_required_timeframes(entry["module"], fallback=entry["timeframe_label"] or "M1")
        entry["required_timeframes"] = required
        schedule_value = resolve_timeframe_value(lowest_timeframe_label(required))
        if schedule_value is not None:
            entry["timeframe_value"] = schedule_value

    config.ACTIVE_STRATEGIES = [entry["key"] for entry in entries]
    config.STRATEGY_KEY = entries[0]["key"]
    config.STRATEGY_MODULE = entries[0]["module_ref"]
    config.TIMEFRAME = entries[0]["timeframe_value"]
    return entries
