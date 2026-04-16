"""
Bot de trading principal para MetaTrader 5.
"""

import importlib
import importlib.util
import inspect
import json
import os
import re
import threading
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone

import MetaTrader5 as mt5
import pandas as pd

import config
import data_feed
import mt5_connection
import trading
from strategy_runtime import (
    TIMEFRAME_MAP,
    apply_strategy_processing as runtime_apply_strategy_processing,
    get_strategy_signal_payload as runtime_get_strategy_signal_payload,
    get_strategy_timeframe as runtime_get_strategy_timeframe,
    normalize_signal as runtime_normalize_signal,
    normalize_signal_payload as runtime_normalize_signal_payload,
    resolve_timeframe_value as runtime_resolve_timeframe_value,
    timeframe_label as runtime_timeframe_label,
)

ORDER_EXECUTION_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Supersistema v1 — estado de runtime
# ---------------------------------------------------------------------------
_db_conn = None          # Conexión SQLite; se inicializa en main() si PERSISTENCE_ENABLED
_db_lock = threading.Lock()  # Lock para serializar escrituras en DB desde múltiples workers


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return str(uuid.uuid4())


def _v1_enabled() -> bool:
    mode = getattr(config, "STRATEGY_RUNTIME_MODE", "legacy")
    return mode in ("dual", "v1_only")


def _persistence_enabled() -> bool:
    return bool(getattr(config, "PERSISTENCE_ENABLED", False)) and _db_conn is not None


def _plan_executor_enabled() -> bool:
    return bool(getattr(config, "PLAN_EXECUTOR_ENABLED", False))


def _get_instance_id(strategy_key: str, symbol: str) -> str:
    return f"{strategy_key}::{symbol}"


def _is_v1_module(module) -> bool:
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


def _resolve_timeframe_value(value):
    return runtime_resolve_timeframe_value(value)


def _timeframe_label(timeframe_value: int) -> str:
    return runtime_timeframe_label(timeframe_value)


def _get_strategy_timeframe(module):
    return runtime_get_strategy_timeframe(module)


def _load_strategy_module(module_ref: str):
    module_ref = (module_ref or "").strip()
    if not module_ref:
        raise ValueError("Referencia de modulo vacia")

    if _looks_like_path(module_ref):
        path = module_ref
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(__file__), path)
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
        strategy_dir = os.path.join(os.path.dirname(__file__), strategy_dir)
    if not os.path.isdir(strategy_dir):
        return {}

    project_root = os.path.dirname(__file__)
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
        strategies_dir = os.path.join(os.path.dirname(__file__), strategy_dir_raw)
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
            continue

        _is_legacy = hasattr(module, "get_last_signal") or hasattr(module, "get_last_signal_payload")
        _is_v1 = _is_v1_module(module)
        _mode = getattr(config, "STRATEGY_RUNTIME_MODE", "legacy")
        if _mode == "v1_only" and not _is_v1:
            continue  # En modo v1_only solo se admiten módulos con decide() + STRATEGY_API_VERSION=1
        if not _is_legacy and not _is_v1:
            continue

        raw_timeframe = entry_dict.get("timeframe") if isinstance(item, dict) else None
        if raw_timeframe is None:
            raw_timeframe = _get_strategy_timeframe(module)
        timeframe_value = _resolve_timeframe_value(raw_timeframe)
        if timeframe_value is None:
            timeframe_value = _resolve_timeframe_value(getattr(config, "TIMEFRAME", None)) or mt5.TIMEFRAME_M1

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
                "timeframe_label": _timeframe_label(timeframe_value) or "M1",
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
                "timeframe_value": mt5.TIMEFRAME_M1,
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

    config.ACTIVE_STRATEGIES = [entry["key"] for entry in entries]
    config.STRATEGY_KEY = entries[0]["key"]
    config.STRATEGY_MODULE = entries[0]["module_ref"]
    config.TIMEFRAME = entries[0]["timeframe_value"]
    return entries


def _make_mt5_data_feed():
    from src.data.mt5_data_feed import MT5DataFeed
    return MT5DataFeed(
        source_mode=config.SOURCE_MODE,
        ma_length=config.MA_LENGTH,
        atr_length=config.ATR_LENGTH,
        atr_mult=config.ATR_MULT,
        supertrend_atr_length=getattr(config, "SUPERTREND_ATR_LENGTH", config.ATR_LENGTH),
        supertrend_mult=getattr(config, "SUPERTREND_MULT", 3.0),
        supertrend_source=getattr(config, "SUPERTREND_SOURCE", "close"),
        supertrend_use_hma=getattr(config, "SUPERTREND_USE_HMA", True),
        hma_length=getattr(config, "HMA_LENGTH", 55),
        tci_fast=getattr(config, "TCI_FAST", 9),
        tci_slow=getattr(config, "TCI_SLOW", 21),
        tci_signal=getattr(config, "TCI_SIGNAL", 5),
    )


def _build_market_dataframe(timeframe_value: int, bars_needed: int, data_feed_impl) -> pd.DataFrame:
    timeframe_str = runtime_timeframe_label(timeframe_value) or "M1"
    return data_feed_impl.get_enriched_df(config.SYMBOL, timeframe_str, bars_needed)


def _apply_strategy_processing(df: pd.DataFrame, module) -> pd.DataFrame:
    return runtime_apply_strategy_processing(
        df,
        module,
        enable_signals=bool(getattr(config, "ENABLE_SIGNALS", True)),
    )


def _normalize_signal(value) -> str:
    return runtime_normalize_signal(value)


def _normalize_signal_payload(value) -> dict:
    return runtime_normalize_signal_payload(value)


def _analyze_strategy(index: int, entry: dict, base_df: pd.DataFrame) -> dict:
    result = {"index": index, "entry": entry, "df": None, "signal": "none", "reason": "", "pyramiding": False, "atr_value": 0.0, "dynamic_sizing": False, "volume_ratio": 0.0, "error": ""}
    try:
        if base_df is None or len(base_df) < 2:
            result["error"] = "No hay suficientes velas"
            return result
        strategy_df = _apply_strategy_processing(base_df, entry["module"])

        params_values = entry.get("params_values") or {}
        accepts_params = entry.get("accepts_params", False)

        if accepts_params and params_values:
            signal_payload = runtime_get_strategy_signal_payload(
                strategy_df,
                entry["module"],
                verbose=False,
                params=params_values,
            )
        else:
            signal_payload = runtime_get_strategy_signal_payload(
                strategy_df,
                entry["module"],
                verbose=False,
            )
        result["df"] = strategy_df
        result["signal"] = signal_payload["signal"]
        result["reason"] = signal_payload["reason"]
        result["pyramiding"] = signal_payload["pyramiding"]
        result["atr_value"] = signal_payload["atr_value"]
        result["dynamic_sizing"] = signal_payload["dynamic_sizing"]
        result["volume_ratio"] = signal_payload["volume_ratio"]
    except Exception as error:
        result["error"] = str(error)
    return result



# ---------------------------------------------------------------------------
# Supersistema v1 — funciones de integración
# ---------------------------------------------------------------------------

def _ensure_strategy_instance(uow, strategy_key: str, symbol: str) -> str:
    """Asegura que existe un registro de instancia en DB. Devuelve instance_id."""
    instance_id = _get_instance_id(strategy_key, symbol)
    existing = uow.strategy_instances.get(instance_id)
    if existing is None:
        now = _now_utc()
        uow.strategy_instances.upsert({
            "instance_id": instance_id,
            "strategy_key": strategy_key,
            "symbol": symbol,
            "status": "active",
            "book_revision": 0,
            "created_at": now,
        })
    return instance_id


def _persist_legacy_execution(
    entry: dict,
    signal: str,
    reason: str,
    iteration_id: str,
):
    """
    Fase 1: persiste trazabilidad del ciclo legacy sin cambiar el comportamiento.
    Crea strategy_instance (si no existe), plan sintético, execution_report y evento.
    """
    if not _persistence_enabled():
        return
    from src.persistence import UnitOfWork
    strategy_key = entry["key"]
    symbol = config.SYMBOL
    instance_id = _get_instance_id(strategy_key, symbol)
    plan_id = _new_id()
    report_id = _new_id()
    now = _now_utc()

    try:
        with _db_lock:
            uow = UnitOfWork(_db_conn)
            with uow.immediate():
                _ensure_strategy_instance(uow, strategy_key, symbol)
                actions_count = 1 if signal != "none" else 0
                uow.plans.insert({
                    "plan_id": plan_id,
                    "instance_id": instance_id,
                    "strategy_key": strategy_key,
                    "symbol": symbol,
                    "iteration_id": iteration_id,
                    "schema_version": 1,
                    "status": "executed",
                    "action_count": actions_count,
                    "reason": reason or f"Señal legacy: {signal}",
                    "plan": {
                        "schema_version": 1,
                        "actions": [{"type": "open_position", "signal": signal}] if signal != "none" else [],
                        "meta": {"origin": "legacy_adapter", "legacy_signal": signal},
                    },
                })
                uow.execution_reports.insert({
                    "report_id": report_id,
                    "plan_id": plan_id,
                    "instance_id": instance_id,
                    "strategy_key": strategy_key,
                    "symbol": symbol,
                    "status": "executed",
                    "summary": f"Legacy signal: {signal}",
                    "stats": {"signal": signal},
                    "report": {"legacy_signal": signal, "reason": reason},
                    "created_at": now,
                })
                uow.event_log.append({
                    "event_type": "legacy_signal_executed",
                    "iteration_id": iteration_id,
                    "mode": "live",
                    "strategy_key": strategy_key,
                    "instance_id": instance_id,
                    "symbol": symbol,
                    "plan_id": plan_id,
                    "report_id": report_id,
                    "payload": {"signal": signal, "reason": reason},
                })
    except Exception:
        pass


def _run_v1_strategy_cycle(
    entry: dict,
    base_df,
    iteration_id: str,
    market_open: bool,
):
    """
    Ciclo completo v1 para una estrategia (legacy o v1 nativa).
    Devuelve dict con signal, reason y un flag executed_order.
    Solo ejecuta si market_open y PLAN_EXECUTOR_ENABLED.
    """
    result = {
        "signal": "none",
        "reason": "",
        "executed_order": False,
        "error": "",
    }
    if not _persistence_enabled():
        return result

    import MetaTrader5 as _mt5
    from src.persistence import UnitOfWork
    from src.runtime import (
        StrategyContextBuilder,
        StrategyStateStore,
        LegacyStrategyAdapter,
        PlanInterpreter,
        PlanValidationError,
        ExecutionEngine,
    )
    from src.broker.mt5_adapter import MT5BrokerAdapter

    strategy_key = entry["key"]
    symbol = config.SYMBOL
    timeframe_label = entry.get("timeframe_label", "M1")
    module = entry["module"]
    magic_number = entry["magic_number"]
    instance_id = _get_instance_id(strategy_key, symbol)

    legacy_defaults = {
        "lot": config.LOT,
        "sl_points": config.SL_POINTS,
        "tp_points": config.TP_POINTS,
    }

    try:
        with _db_lock:
            uow = UnitOfWork(_db_conn)
            _ensure_strategy_instance(uow, strategy_key, symbol)
            _db_conn.commit()

        uow = UnitOfWork(_db_conn)
        state_store = StrategyStateStore(uow)
        context_builder = StrategyContextBuilder(_mt5, uow)

        # Cargar state
        strategy_state, state_revision = state_store.load(instance_id)

        # Construir context
        context = context_builder.build(
            strategy_key=strategy_key,
            symbol=symbol,
            timeframe_label=timeframe_label,
            df=base_df,
            instance_id=instance_id,
            state_revision=state_revision,
            iteration_id=iteration_id,
            legacy_defaults=legacy_defaults,
        )

        # Obtener initial_state si es la primera vez con módulo v1
        if state_revision == 0 and _is_v1_module(module) and hasattr(module, "initial_state"):
            try:
                strategy_state = module.initial_state(context) or {}
            except Exception:
                strategy_state = {}

        # Llamar a decide()
        if _is_v1_module(module):
            raw_decision = module.decide(context, strategy_state)
        else:
            adapter = LegacyStrategyAdapter(module, timeframe_label)
            raw_decision = adapter.decide(context, strategy_state)

        plan = raw_decision.get("plan", {})
        next_state = raw_decision.get("next_state", strategy_state)

        # Extraer señal para compatibilidad con métricas de log
        meta_signal = plan.get("meta", {}).get("legacy_signal", "")
        actions = plan.get("actions", [])
        if not meta_signal and actions:
            first_action = actions[0]
            side = first_action.get("side", "")
            if side == "long":
                meta_signal = "buy"
            elif side == "short":
                meta_signal = "sell"
            else:
                meta_signal = "none"
        result["signal"] = meta_signal or "none"
        result["reason"] = plan.get("reason", "")

        plan_id = plan.get("plan_id", _new_id())
        plan["plan_id"] = plan_id

        # Persistir plan
        with _db_lock:
            uow2 = UnitOfWork(_db_conn)
            with uow2.immediate():
                uow2.plans.insert({
                    "plan_id": plan_id,
                    "instance_id": instance_id,
                    "strategy_key": strategy_key,
                    "symbol": symbol,
                    "iteration_id": iteration_id,
                    "schema_version": plan.get("schema_version", 1),
                    "status": "validated",
                    "action_count": len(actions),
                    "state_revision_before": state_revision,
                    "reason": plan.get("reason", ""),
                    "plan": plan,
                })
                uow2.event_log.append({
                    "event_type": "plan_received",
                    "iteration_id": iteration_id,
                    "mode": "live",
                    "strategy_key": strategy_key,
                    "instance_id": instance_id,
                    "symbol": symbol,
                    "plan_id": plan_id,
                    "payload": {"action_count": len(actions), "signal": meta_signal},
                })

        # Ejecutar si habilitado y mercado abierto
        if _plan_executor_enabled() and market_open and actions:
            interpreter = PlanInterpreter()
            try:
                normalized = interpreter.validate_and_normalize(plan, context)
            except PlanValidationError as exc:
                with _db_lock:
                    uow3 = UnitOfWork(_db_conn)
                    uow3.plans.update_status(plan_id, "rejected_structural")
                    _db_conn.commit()
                result["error"] = f"Plan inválido: {exc}"
                return result

            engine = ExecutionEngine(
                broker=MT5BrokerAdapter(),
                uow=UnitOfWork(_db_conn),
                symbol=symbol,
                magic_number=magic_number,
                strategy_key=strategy_key,
                instance_id=instance_id,
            )

            with ORDER_EXECUTION_LOCK:
                exec_report = engine.execute_plan(
                    plan=plan,
                    normalized_actions=normalized,
                    state_revision_before=state_revision,
                    iteration_id=iteration_id,
                )

            result["executed_order"] = exec_report.get("status") in ("executed", "partially_executed")

        # Persistir next_state
        new_revision = state_revision + 1
        with _db_lock:
            uow4 = UnitOfWork(_db_conn)
            with uow4.immediate():
                uow4.strategy_state.upsert({
                    "instance_id": instance_id,
                    "strategy_key": strategy_key,
                    "symbol": symbol,
                    "schema_version": 1,
                    "revision": new_revision,
                    "last_decision_id": iteration_id,
                    "state": {"strategy_state": next_state},
                })
                uow4.plans.update_status(
                    plan_id,
                    "executed" if result["executed_order"] else "executed",
                )

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _resolve_max_workers(strategy_count: int) -> int:
    try:
        configured = int(getattr(config, "STRATEGY_MAX_WORKERS", 0) or 0)
    except Exception:
        configured = 0
    if configured > 0:
        return max(1, min(strategy_count, configured))
    return max(1, min(strategy_count, 8))


def _resolve_analysis_timeout() -> float:
    try:
        timeout = float(getattr(config, "STRATEGY_ANALYSIS_TIMEOUT_SECONDS", 15) or 15)
    except Exception:
        timeout = 15.0
    return max(1.0, timeout)


def _resolve_max_orders_per_iteration(strategy_count: int) -> int:
    try:
        value = int(getattr(config, "MAX_ORDERS_PER_ITERATION", strategy_count) or strategy_count)
    except Exception:
        value = strategy_count
    return max(1, min(strategy_count, value))


def run_bot_loop(strategy_entries: list, data_feed_impl=None):
    if data_feed_impl is None:
        data_feed_impl = _make_mt5_data_feed()
    max_workers = _resolve_max_workers(len(strategy_entries))
    sleep_seconds = max(1, int(getattr(config, "SLEEP_SECONDS", 10) or 10))
    analysis_timeout = _resolve_analysis_timeout()
    max_orders_per_iteration = _resolve_max_orders_per_iteration(len(strategy_entries))
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="strategy") if max_workers > 1 else None

    last_analyzed_ts = {
        entry["key"]: 0.0 for entry in strategy_entries
    }

    try:
        while True:
            start_ts = time.time()
            try:
                market_open, market_status_msg = trading.is_market_open(config.SYMBOL)

                market_cache = {}
                for timeframe_value in sorted({int(entry["timeframe_value"]) for entry in strategy_entries}):
                    market_cache[timeframe_value] = _build_market_dataframe(timeframe_value, config.BARS_HISTORY, data_feed_impl)

                # Fair scheduler: primero se analizan las estrategias que llevan mas tiempo sin correr.
                scheduled_items = sorted(
                    list(enumerate(strategy_entries)),
                    key=lambda item: (last_analyzed_ts.get(item[1]["key"], 0.0), item[0]),
                )

                results = {}
                if executor is not None:
                    futures = {}
                    for idx, entry in scheduled_items:
                        futures[executor.submit(_analyze_strategy, idx, entry, market_cache.get(entry["timeframe_value"]))] = idx
                    done, pending = wait(futures.keys(), timeout=analysis_timeout)
                    for future in done:
                        idx = futures[future]
                        entry = strategy_entries[idx]
                        try:
                            item = future.result()
                            results[item["index"]] = item
                            key = item["entry"]["key"]
                            last_analyzed_ts[key] = time.time()
                        except Exception as error:
                            results[idx] = {
                                "index": idx,
                                "entry": entry,
                                "df": None,
                                "signal": "none",
                                "error": f"Error de worker: {error}",
                            }
                    for future in pending:
                        idx = futures[future]
                        entry = strategy_entries[idx]
                        future.cancel()
                        results[idx] = {
                            "index": idx,
                            "entry": entry,
                            "df": None,
                            "signal": "none",
                            "error": f"Timeout de analisis (> {analysis_timeout:.1f}s)",
                        }
                else:
                    for idx, entry in scheduled_items:
                        item = _analyze_strategy(idx, entry, market_cache.get(entry["timeframe_value"]))
                        results[idx] = item
                        last_analyzed_ts[entry["key"]] = time.time()

                iteration_id = _new_id()
                executed_orders = 0
                runtime_mode = getattr(config, "STRATEGY_RUNTIME_MODE", "legacy")
                use_v1 = (
                    runtime_mode == "v1_only"
                    and _plan_executor_enabled()
                    and _persistence_enabled()
                )

                for idx, _ in scheduled_items:
                    result = results.get(idx)
                    if not result:
                        continue
                    entry = result["entry"]
                    if result.get("error"):
                        continue

                    if not market_open:
                        continue

                    if executed_orders >= max_orders_per_iteration:
                        continue

                    # ----------------------------------------------------------
                    # Ruta exclusiva v1: todos los módulos pasan por el ciclo v1.
                    # El módulo decide() internamente si actúa o no.
                    # ----------------------------------------------------------
                    if use_v1:
                        v1_result = _run_v1_strategy_cycle(
                            entry,
                            market_cache.get(entry["timeframe_value"]),
                            iteration_id,
                            market_open,
                        )
                        if v1_result.get("executed_order"):
                            executed_orders += 1
                        continue

                    # ----------------------------------------------------------
                    # Ruta legacy (solo cuando PLAN_EXECUTOR_ENABLED = False)
                    # ----------------------------------------------------------
                    signal = result["signal"]
                    reason = str(result.get("reason") or "").strip()

                    if signal == "none":
                        continue

                    pyramiding     = result.get("pyramiding", False)
                    atr_value      = result.get("atr_value", 0.0)
                    dynamic_sizing = result.get("dynamic_sizing", False)
                    volume_ratio   = result.get("volume_ratio", 0.0)

                    with ORDER_EXECUTION_LOCK:
                        if pyramiding and atr_value > 0 and signal == "buy":
                            if dynamic_sizing and volume_ratio > 0 and atr_value > 0:
                                from src.broker.mt5_adapter import MT5BrokerAdapter as _Adapter
                                _broker = _Adapter()
                                account = _broker.get_account_info()
                                balance = account.balance if account is not None else 0.0
                                instrument_info = _broker.get_instrument_info(config.SYMBOL)
                                if instrument_info is not None and balance > 0:
                                    raw_lot = trading.calculate_dynamic_lot(
                                        atr_value, volume_ratio, instrument_info, balance
                                    )
                                else:
                                    raw_lot = 0.0
                                lot = raw_lot if raw_lot > 0 else config.LOT
                            else:
                                lot = config.LOT
                                balance = None

                            trading.apply_pyramid_signal(
                                config.SYMBOL,
                                entry["magic_number"],
                                atr_value,
                                lot,
                                strategy_key=entry["key"],
                                strategy_label=entry["label"],
                                signal_reason=reason,
                                balance=balance if dynamic_sizing else None,
                            )
                        else:
                            trading.apply_signal(
                                config.SYMBOL,
                                signal,
                                config.LOT,
                                config.SL_POINTS,
                                config.TP_POINTS,
                                entry["magic_number"],
                                strategy_key=entry["key"],
                                strategy_label=entry["label"],
                                signal_reason=reason,
                            )
                    executed_orders += 1

                elapsed = time.time() - start_ts
                time.sleep(sleep_seconds)

            except Exception as error:
                time.sleep(sleep_seconds)

    except KeyboardInterrupt:
        pass
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


def main():
    global _db_conn

    if _resolve_timeframe_value(getattr(config, "TIMEFRAME", None)) is None:
        config.TIMEFRAME = mt5.TIMEFRAME_M1

    # Bootstrap persistencia v1
    if getattr(config, "PERSISTENCE_ENABLED", False):
        try:
            from src.persistence import bootstrap_persistence
            db_path = getattr(config, "PERSISTENCE_DB_PATH", "trading_bot.db")
            _db_conn = bootstrap_persistence(db_path)
        except Exception:
            _db_conn = None

    try:
        strategy_entries = load_active_strategies()
    except Exception as error:
        return

    try:
        mt5_connection.initialize_mt5()
    except Exception as error:
        return

    try:
        mt5_connection.check_symbol(config.SYMBOL)
    except Exception as error:
        mt5.shutdown()
        return

    run_bot_loop(strategy_entries)
    mt5.shutdown()
    if _db_conn is not None:
        try:
            _db_conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
