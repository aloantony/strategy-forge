# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Entrypoint del bot en vivo (headless): carga estrategias activas y ejecuta el loop
de análisis/órdenes. Hoy requiere el terminal MT5; para entornos sin MT5 usa el
servidor (uvicorn server.app:app) con el broker paper.
"""

import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone

from backend.brokers.mt5_import import mt5
import pandas as pd

from backend.core import config
from backend.brokers.mt5 import connection as mt5_connection
from backend.brokers.mt5 import trading
from backend.strategy.loader import is_v1_module, load_active_strategies
from backend.strategy.runtime import (
    TIMEFRAME_MAP,
    TIMEFRAME_MINUTES,
    analyze_signal as runtime_analyze_signal,
    is_mtf_module as runtime_is_mtf_module,
    resolve_timeframe_value as runtime_resolve_timeframe_value,
    timeframe_to_seconds as runtime_timeframe_to_seconds,
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


def _persistence_enabled() -> bool:
    return bool(getattr(config, "PERSISTENCE_ENABLED", False)) and _db_conn is not None


def _plan_executor_enabled() -> bool:
    return bool(getattr(config, "PLAN_EXECUTOR_ENABLED", False))


def _get_instance_id(strategy_key: str, symbol: str) -> str:
    return f"{strategy_key}::{symbol}"


def _make_mt5_data_feed():
    from backend.data.mt5_data_feed import MT5DataFeed
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


def _build_market_dataframe(timeframe_label: str, bars_needed: int, data_feed_impl) -> pd.DataFrame:
    return data_feed_impl.get_enriched_df(config.SYMBOL, timeframe_label or "M1", bars_needed)


def _entry_required_timeframes(entry: dict) -> list[str]:
    return list(entry.get("required_timeframes") or [entry.get("timeframe_label") or "M1"])


def _entry_frames(entry: dict, market_cache: dict) -> dict:
    return {
        tf: market_cache.get(tf)
        for tf in _entry_required_timeframes(entry)
        if isinstance(market_cache.get(tf), pd.DataFrame)
    }


def _analyze_strategy(index: int, entry: dict, market_cache: dict) -> dict:
    result = {"index": index, "entry": entry, "signal": "none", "reason": "", "payload": None, "error": ""}
    try:
        module = entry["module"]
        primary = entry.get("timeframe_label") or "M1"
        params_values = entry.get("params_values") or {}
        params = params_values if (entry.get("accepts_params") and params_values) else None
        enable_signals = bool(getattr(config, "ENABLE_SIGNALS", True))

        if runtime_is_mtf_module(module):
            data = _entry_frames(entry, market_cache)
            base_df = data.get(primary)
        else:
            data = market_cache.get(primary)
            base_df = data

        if base_df is None or len(base_df) < 2:
            result["error"] = "No hay suficientes velas"
            return result

        payload = runtime_analyze_signal(
            module, data, enable_signals=enable_signals, verbose=False, params=params
        )
        result["payload"] = payload
        result["signal"] = payload["signal"]
        result["reason"] = payload["reason"]
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


def _run_v1_strategy_cycle(
    entry: dict,
    base_df,
    iteration_id: str,
    market_open: bool,
    mtf_frames: dict | None = None,
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

    from backend.brokers.mt5_import import mt5 as _mt5
    from backend.persistence import UnitOfWork
    from backend.runtime import (
        StrategyContextBuilder,
        StrategyStateStore,
        LegacyStrategyAdapter,
        PlanInterpreter,
        PlanValidationError,
        ExecutionEngine,
    )
    from backend.brokers.mt5.adapter import MT5BrokerAdapter

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
        if state_revision == 0 and is_v1_module(module) and hasattr(module, "initial_state"):
            try:
                strategy_state = module.initial_state(context) or {}
            except Exception:
                strategy_state = {}

        # Llamar a decide()
        if is_v1_module(module):
            raw_decision = module.decide(context, strategy_state)
        else:
            adapter = LegacyStrategyAdapter(module, timeframe_label, frames=mtf_frames)
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

        # Persistir next_state. El status final del plan lo fija ExecutionEngine
        # al ejecutar; un plan no ejecutado se queda en "validated".
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
    min_tf_value = min(entry["timeframe_value"] for entry in strategy_entries)
    sleep_seconds = runtime_timeframe_to_seconds(min_tf_value)
    analysis_timeout = _resolve_analysis_timeout()
    max_orders_per_iteration = _resolve_max_orders_per_iteration(len(strategy_entries))
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="strategy") if max_workers > 1 else None

    last_analyzed_ts = {
        entry["key"]: 0.0 for entry in strategy_entries
    }

    needed_labels = set()
    for entry in strategy_entries:
        needed_labels.update(_entry_required_timeframes(entry))

    try:
        while True:
            try:
                market_open, market_status_msg = trading.is_market_open(config.SYMBOL)

                market_cache = {}
                for label in sorted(needed_labels, key=lambda l: TIMEFRAME_MINUTES.get(l, 1)):
                    market_cache[label] = _build_market_dataframe(label, config.BARS_HISTORY, data_feed_impl)

                # Fair scheduler: primero se analizan las estrategias que llevan mas tiempo sin correr.
                scheduled_items = sorted(
                    list(enumerate(strategy_entries)),
                    key=lambda item: (last_analyzed_ts.get(item[1]["key"], 0.0), item[0]),
                )

                results = {}
                if executor is not None:
                    futures = {}
                    for idx, entry in scheduled_items:
                        futures[executor.submit(_analyze_strategy, idx, entry, market_cache)] = idx
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
                        item = _analyze_strategy(idx, entry, market_cache)
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
                        print(f"[main] {entry['key']}: {result['error']}")
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
                        mtf_frames = (
                            _entry_frames(entry, market_cache)
                            if runtime_is_mtf_module(entry["module"]) else None
                        )
                        v1_result = _run_v1_strategy_cycle(
                            entry,
                            market_cache.get(entry.get("timeframe_label") or "M1"),
                            iteration_id,
                            market_open,
                            mtf_frames=mtf_frames,
                        )
                        if v1_result.get("error"):
                            print(f"[main] {entry['key']} (v1): {v1_result['error']}")
                        if v1_result.get("executed_order"):
                            executed_orders += 1
                        continue

                    # ----------------------------------------------------------
                    # Ruta legacy (solo cuando PLAN_EXECUTOR_ENABLED = False)
                    # ----------------------------------------------------------
                    payload = result.get("payload") or {}
                    signal = result["signal"]
                    reason = str(result.get("reason") or "").strip()

                    if signal == "none":
                        continue

                    pyramiding = bool(payload.get("pyramiding"))
                    atr_value = float(payload.get("atr_value") or 0.0)

                    with ORDER_EXECUTION_LOCK:
                        if pyramiding and atr_value > 0:
                            direction = 1 if signal == "buy" else -1
                            risk_pct = float(payload.get("risk_pct") or 0.0)
                            volume_ratio = float(payload.get("volume_ratio") or 0.0)
                            dynamic_sizing = bool(payload.get("dynamic_sizing")) and volume_ratio > 0
                            sl_atr_mult = float(payload.get("sl_atr_mult") or 1.0)

                            lot = config.LOT
                            balance = None
                            if risk_pct > 0 or dynamic_sizing:
                                from backend.brokers.mt5.adapter import MT5BrokerAdapter as _Adapter
                                _broker = _Adapter()
                                account = _broker.get_account_info()
                                balance = account.balance if account is not None else 0.0
                                instrument_info = _broker.get_instrument_info(config.SYMBOL)
                                raw_lot = 0.0
                                if instrument_info is not None and balance > 0:
                                    if risk_pct > 0:
                                        raw_lot = trading.calculate_risk_lot(
                                            atr_value, risk_pct, instrument_info, balance,
                                            sl_atr_mult=sl_atr_mult,
                                        )
                                    else:
                                        raw_lot = trading.calculate_dynamic_lot(
                                            atr_value, volume_ratio, instrument_info, balance
                                        )
                                lot = raw_lot if raw_lot > 0 else config.LOT

                            trading.apply_pyramid_signal(
                                config.SYMBOL,
                                entry["magic_number"],
                                atr_value,
                                lot,
                                strategy_key=entry["key"],
                                strategy_label=entry["label"],
                                signal_reason=reason,
                                balance=balance,
                                sl_atr_mult=sl_atr_mult,
                                tp_atr_mult=float(payload.get("tp_atr_mult") or 2.0),
                                pyramid_atr_mult=float(payload.get("pyramid_atr_mult") or 0.5),
                                max_entries=payload.get("max_entries"),
                                entry_index=payload.get("entry_index"),
                                direction=direction,
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

                time.sleep(sleep_seconds)

            except Exception as error:
                print(f"[main] Error en el ciclo del bot: {error}")
                time.sleep(sleep_seconds)

    except KeyboardInterrupt:
        pass
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


def main():
    global _db_conn

    if mt5 is None:
        print(
            "ERROR: MT5 no está disponible. backend.main requiere el terminal MT5 (Windows).\n"
            "Para correr sin MT5 arranca el servidor con el broker paper:\n"
            "    TRADING_BROKER=paper uvicorn server.app:app",
            file=sys.stderr,
        )
        sys.exit(1)

    if runtime_resolve_timeframe_value(getattr(config, "TIMEFRAME", None)) is None:
        config.TIMEFRAME = TIMEFRAME_MAP["M1"]

    # Bootstrap persistencia v1
    if getattr(config, "PERSISTENCE_ENABLED", False):
        try:
            from backend.persistence import bootstrap_persistence
            db_path = getattr(config, "PERSISTENCE_DB_PATH", "trading_bot.db")
            _db_conn = bootstrap_persistence(db_path)
        except Exception as error:
            print(f"[main] Persistencia deshabilitada (error al inicializar): {error}", file=sys.stderr)
            _db_conn = None

    try:
        strategy_entries = load_active_strategies()
    except Exception as error:
        print(f"ERROR: no se pudieron cargar las estrategias: {error}", file=sys.stderr)
        return

    try:
        mt5_connection.initialize_mt5()
    except Exception as error:
        print(f"ERROR: no se pudo inicializar MT5: {error}", file=sys.stderr)
        return

    try:
        mt5_connection.check_symbol(config.SYMBOL)
    except Exception as error:
        print(f"ERROR: símbolo no disponible ({config.SYMBOL}): {error}", file=sys.stderr)
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
