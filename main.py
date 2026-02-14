"""
Bot de trading principal para MetaTrader 5.
"""

import importlib
import importlib.util
import os
import re
import threading
import time
import traceback
import zlib
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd

import config
import data_feed
import mt5_connection
import trading


TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

ORDER_EXECUTION_LOCK = threading.Lock()


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
    if value is None:
        return None
    if isinstance(value, str):
        return TIMEFRAME_MAP.get(value.strip().upper())
    if isinstance(value, int) and value in TIMEFRAME_MAP.values():
        return value
    return None


def _timeframe_label(timeframe_value: int) -> str:
    reverse_map = {v: k for k, v in TIMEFRAME_MAP.items()}
    return reverse_map.get(timeframe_value, "")


def _get_strategy_timeframe(module):
    if module is None:
        return None
    if hasattr(module, "get_timeframe"):
        try:
            return module.get_timeframe()
        except Exception:
            return None
    for key in ("TIMEFRAME", "STRATEGY_TIMEFRAME", "TIMEFRAME_STR"):
        if hasattr(module, key):
            try:
                return getattr(module, key)
            except Exception:
                return None
    return None


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


def load_active_strategies():
    default_key = _slugify(getattr(config, "STRATEGY_KEY", "ema_rsi_trend") or "ema_rsi_trend")
    default_module_ref = str(getattr(config, "STRATEGY_MODULE", "") or "").strip()
    if not default_module_ref:
        default_module_ref = f"strategies.strategy_{default_key}"

    active_raw = getattr(config, "ACTIVE_STRATEGIES", None)
    requested = list(active_raw) if isinstance(active_raw, (list, tuple, set)) and active_raw else [default_key]
    discovered_map = _discover_strategy_modules_from_dir()

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
            print(f"[WARN] No se pudo cargar estrategia '{label}' ({key}): {last_error or 'sin detalle'}")
            continue

        if not hasattr(module, "get_last_signal") and not hasattr(module, "get_last_signal_payload"):
            print(
                f"[WARN] Estrategia '{label}' ({key}) omitida: "
                "falta get_last_signal() o get_last_signal_payload()."
            )
            continue

        raw_timeframe = entry_dict.get("timeframe") if isinstance(item, dict) else None
        if raw_timeframe is None:
            raw_timeframe = _get_strategy_timeframe(module)
        timeframe_value = _resolve_timeframe_value(raw_timeframe)
        if timeframe_value is None:
            timeframe_value = _resolve_timeframe_value(getattr(config, "TIMEFRAME", None)) or mt5.TIMEFRAME_M1

        entries.append(
            {
                "key": key,
                "label": label or key,
                "module_ref": module_ref,
                "module": module,
                "timeframe_value": timeframe_value,
                "timeframe_label": _timeframe_label(timeframe_value) or "M1",
                "magic_override": entry_dict.get("magic_number") if isinstance(item, dict) else None,
            }
        )

    if not entries:
        fallback_key = default_key or "ema_rsi_trend"
        if discovered_map:
            fallback_key = next(iter(discovered_map.keys()), fallback_key)
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
        entries = [
            {
                "key": fallback_key,
                "label": fallback_key,
                "module_ref": module_ref,
                "module": module,
                "timeframe_value": mt5.TIMEFRAME_M1,
                "timeframe_label": "M1",
                "magic_override": None,
            }
        ]
        print(f"[WARN] Sin estrategias validas. Se usa '{fallback_key}' por defecto.")

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


def _build_market_dataframe(timeframe_value: int, bars_needed: int) -> pd.DataFrame:
    df = data_feed.get_rates_df(config.SYMBOL, timeframe_value, bars_needed)
    df = data_feed.add_source_columns(df, config.SOURCE_MODE)
    df = data_feed.add_baseline_bands(df, config.MA_LENGTH, config.ATR_LENGTH, config.ATR_MULT)
    df = data_feed.add_supertrend(
        df,
        atr_length=getattr(config, "SUPERTREND_ATR_LENGTH", config.ATR_LENGTH),
        atr_mult=getattr(config, "SUPERTREND_MULT", 3.0),
        source_col=getattr(config, "SUPERTREND_SOURCE", "close"),
        use_hma=getattr(config, "SUPERTREND_USE_HMA", True),
        hma_length=getattr(config, "HMA_LENGTH", 55),
    )
    df = data_feed.add_tci(
        df,
        fast_length=getattr(config, "TCI_FAST", 9),
        slow_length=getattr(config, "TCI_SLOW", 21),
        signal_length=getattr(config, "TCI_SIGNAL", 5),
    )
    return df


def _apply_strategy_processing(df: pd.DataFrame, module) -> pd.DataFrame:
    out = df.copy()
    if hasattr(module, "prepare_dataframe"):
        candidate = module.prepare_dataframe(out)
        if isinstance(candidate, pd.DataFrame):
            out = candidate
    if hasattr(module, "compute_dir1_and_signals"):
        candidate = module.compute_dir1_and_signals(out, config.ENABLE_SIGNALS)
        if isinstance(candidate, pd.DataFrame):
            out = candidate
    elif hasattr(module, "compute_signals"):
        candidate = module.compute_signals(out, config.ENABLE_SIGNALS)
        if isinstance(candidate, pd.DataFrame):
            out = candidate
    return out


def _normalize_signal(value) -> str:
    signal = str(value or "").strip().lower()
    return signal if signal in {"buy", "sell", "none"} else "none"


def _normalize_signal_payload(value) -> dict:
    signal_raw = value
    reason_raw = ""

    if isinstance(value, dict):
        signal_raw = (
            value.get("signal")
            or value.get("side")
            or value.get("action")
            or value.get("decision")
            or "none"
        )
        reason_raw = (
            value.get("reason")
            or value.get("motivo")
            or value.get("message")
            or value.get("detail")
            or value.get("why")
            or ""
        )
    elif isinstance(value, (tuple, list)):
        if len(value) > 0:
            signal_raw = value[0]
        if len(value) > 1:
            reason_raw = value[1]

    reason = str(reason_raw or "").strip()
    if len(reason) > 160:
        reason = reason[:157].rstrip() + "..."

    return {
        "signal": _normalize_signal(signal_raw),
        "reason": reason,
    }


def _analyze_strategy(index: int, entry: dict, base_df: pd.DataFrame) -> dict:
    result = {"index": index, "entry": entry, "df": None, "signal": "none", "reason": "", "error": ""}
    try:
        if base_df is None or len(base_df) < 2:
            result["error"] = "No hay suficientes velas"
            return result
        strategy_df = _apply_strategy_processing(base_df, entry["module"])
        raw_payload = None
        if bool(getattr(config, "TEST_MODE", False)) and hasattr(entry["module"], "get_test_signal"):
            raw_payload = {"signal": entry["module"].get_test_signal(), "reason": "test_mode"}
        elif hasattr(entry["module"], "get_last_signal_payload"):
            try:
                raw_payload = entry["module"].get_last_signal_payload(strategy_df, verbose=False)
            except TypeError:
                raw_payload = entry["module"].get_last_signal_payload(strategy_df)
        else:
            try:
                raw_payload = entry["module"].get_last_signal(strategy_df, verbose=False)
            except TypeError:
                raw_payload = entry["module"].get_last_signal(strategy_df)
        signal_payload = _normalize_signal_payload(raw_payload)
        result["df"] = strategy_df
        result["signal"] = signal_payload["signal"]
        result["reason"] = signal_payload["reason"]
    except Exception as error:
        result["error"] = str(error)
    return result


def _format_number(value, digits: int = 2) -> str:
    try:
        if pd.isna(value):
            return "N/A"
        return f"{float(value):.{digits}f}"
    except Exception:
        return "N/A"


def print_strategy_status(entry: dict, df: pd.DataFrame, signal: str, reason: str = ""):
    if df is None or len(df) < 2:
        print(f"[WARN] [{entry['label']}] Sin datos suficientes.")
        return

    row = df.iloc[len(df) - 2]
    print("\n" + "=" * 84)
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{entry['label']} ({entry['key']}) | TF {entry['timeframe_label']} | Magic {entry['magic_number']}"
    )
    print("=" * 84)
    print(f"   Time: {row.get('time', 'N/A')}")
    print(
        f"   OHLC: O={_format_number(row.get('open'))} H={_format_number(row.get('high'))} "
        f"L={_format_number(row.get('low'))} C={_format_number(row.get('close'))}"
    )
    if "up_sig" in df.columns or "dn_sig" in df.columns:
        print(f"   Up_Sig={row.get('up_sig', 'N/A')} | Dn_Sig={row.get('dn_sig', 'N/A')}")
    print(f"   Senal: {signal.upper() if signal != 'none' else 'NINGUNA'}")
    if reason:
        print(f"   Motivo: {reason}")

    position_dir = trading.get_open_position_direction(config.SYMBOL, entry["magic_number"])
    position_info = trading.get_position_info(config.SYMBOL, entry["magic_number"])
    position_str = "[+] BUY" if position_dir == 1 else "[-] SELL" if position_dir == -1 else "[0] SIN POSICION"
    print(f"   Posicion: {position_str}")
    if position_info:
        print(f"   Ticket: {position_info.get('ticket')}")
        print(f"   Profit: {_format_number(position_info.get('profit'))}")
    print("=" * 84)


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


def run_bot_loop(strategy_entries: list):
    print("Iniciando bucle del bot...")
    print(f"Estrategias activas: {len(strategy_entries)}")

    max_workers = _resolve_max_workers(len(strategy_entries))
    sleep_seconds = max(1, int(getattr(config, "SLEEP_SECONDS", 10) or 10))
    analysis_timeout = _resolve_analysis_timeout()
    max_orders_per_iteration = _resolve_max_orders_per_iteration(len(strategy_entries))
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="strategy") if max_workers > 1 else None
    print(f"Workers de analisis: {max_workers}")
    print(f"Timeout analisis por ciclo: {analysis_timeout:.1f}s")
    print(f"Max ordenes por ciclo: {max_orders_per_iteration}")
    print("Planificador: oldest-first (prioriza estrategias con mayor espera).")

    last_analyzed_ts = {
        entry["key"]: 0.0 for entry in strategy_entries
    }

    try:
        while True:
            start_ts = time.time()
            try:
                test_mode = bool(getattr(config, "TEST_MODE", False))
                if test_mode:
                    market_open, market_status_msg = True, "TEST_MODE (sin check)"
                else:
                    market_open, market_status_msg = trading.is_market_open(config.SYMBOL)

                market_cache = {}
                for timeframe_value in sorted({int(entry["timeframe_value"]) for entry in strategy_entries}):
                    market_cache[timeframe_value] = _build_market_dataframe(timeframe_value, config.BARS_HISTORY)

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

                print("\n" + "-" * 84)
                print(f"{'[OK]' if market_open else '[!!]'} ESTADO DEL MERCADO: {market_status_msg}")
                if not market_open:
                    print("   [WARN] Se analiza, pero no se ejecutan operaciones.")
                print("-" * 84)

                executed_orders = 0
                for idx, _ in scheduled_items:
                    result = results.get(idx)
                    if not result:
                        continue
                    entry = result["entry"]
                    if result.get("error"):
                        print(f"[ERROR] [{entry['label']}] {result['error']}")
                        continue

                    signal = result["signal"]
                    reason = str(result.get("reason") or "").strip()
                    print_strategy_status(entry, result["df"], signal, reason=reason)

                    if signal == "none":
                        print(f"[WAIT] [{entry['label']}] Sin accion requerida.")
                        continue
                    if not market_open:
                        reason_txt = f" | motivo: {reason}" if reason else ""
                        print(
                            f"[WAIT] [{entry['label']}] Senal {signal.upper()} detectada "
                            f"pero mercado cerrado.{reason_txt}"
                        )
                        continue

                    if executed_orders >= max_orders_per_iteration:
                        print(
                            f"[SKIP] [{entry['label']}] Limite de ordenes alcanzado "
                            f"({max_orders_per_iteration} por ciclo)."
                        )
                        continue

                    reason_txt = f" | motivo: {reason}" if reason else ""
                    print(f">>> ACCION [{entry['label']}]: Ejecutando {signal.upper()}{reason_txt}")
                    with ORDER_EXECUTION_LOCK:
                        trading.apply_signal(
                            config.SYMBOL,
                            signal,
                            config.LOT,
                            config.SL_POINTS,
                            config.TP_POINTS,
                            entry["magic_number"],
                            timeframe_value=entry["timeframe_value"],
                            strategy_key=entry["key"],
                            strategy_label=entry["label"],
                            signal_reason=reason,
                        )
                    executed_orders += 1

                elapsed = time.time() - start_ts
                print(f"\n[...] Iteracion en {elapsed:.2f}s. Esperando {sleep_seconds}s.\n")
                time.sleep(sleep_seconds)

            except Exception as error:
                print(f"\n[ERROR] Error en el bucle: {error}")
                traceback.print_exc()
                time.sleep(sleep_seconds)

    except KeyboardInterrupt:
        print("\n\nBot detenido por el usuario")
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


def main():
    if _resolve_timeframe_value(getattr(config, "TIMEFRAME", None)) is None:
        config.TIMEFRAME = mt5.TIMEFRAME_M1

    try:
        strategy_entries = load_active_strategies()
    except Exception as error:
        print(f"Error al cargar estrategias: {error}")
        traceback.print_exc()
        return

    try:
        mt5_connection.initialize_mt5()
    except Exception as error:
        print(f"Error al inicializar MT5: {error}")
        return

    try:
        mt5_connection.check_symbol(config.SYMBOL)
    except Exception as error:
        print(f"Error al verificar simbolo: {error}")
        mt5.shutdown()
        return

    config.print_config()
    print("\n=== ESTRATEGIAS ACTIVAS ===")
    for entry in strategy_entries:
        print(
            f"- {entry['label']} ({entry['key']}) | modulo={entry['module_ref']} | "
            f"tf={entry['timeframe_label']} | magic={entry['magic_number']}"
        )
    print("===========================\n")

    run_bot_loop(strategy_entries)
    mt5.shutdown()


if __name__ == "__main__":
    main()
