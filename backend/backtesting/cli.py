"""
CLI para ejecutar utilidades de backtesting desde el paquete.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import sys
import zlib
from datetime import datetime

from backend.brokers.mt5_import import mt5

from backend.core import config
from backend.brokers.mt5 import connection as mt5_connection
from backend.strategy.runtime import get_strategy_timeframe, resolve_timeframe_value, timeframe_label

from . import runtime


def _parse_date(value: str, *, end_of_day: bool = False) -> datetime:
    dt = datetime.strptime(str(value or "").strip(), "%Y-%m-%d")
    if end_of_day:
        return dt.replace(hour=23, minute=59, second=59)
    return dt


def _default_timeframe_label() -> str:
    configured = getattr(config, "TIMEFRAME", None)
    label = timeframe_label(configured) if isinstance(configured, int) else str(configured or "").strip().upper()
    return label or "M1"


def _load_strategy_module(module_ref: str):
    ref = str(module_ref or "").strip()
    if not ref:
        raise ValueError("Debe indicar un módulo de estrategia")

    is_path_like = ref.endswith(".py") or any(sep in ref for sep in (os.sep, os.altsep) if sep)
    if is_path_like:
        path = os.path.abspath(ref)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"No existe el archivo de estrategia: {path}")
        module_name = (
            f"backtest_strategy_{os.path.splitext(os.path.basename(path))[0]}_"
            f"{zlib.crc32(path.encode('utf-8')):08x}"
        )
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"No se pudo crear spec para {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    importlib.invalidate_caches()
    return importlib.reload(importlib.import_module(ref))


def _resolve_strategy_module_ref(strategy_key: str, strategy_module: str) -> str:
    explicit = str(strategy_module or "").strip()
    if explicit:
        return explicit

    key = str(strategy_key or getattr(config, "STRATEGY_KEY", "") or "").strip()
    if key:
        return f"strategies.strategy_{key}"

    configured = str(getattr(config, "STRATEGY_MODULE", "") or "").strip()
    if configured:
        return configured

    raise ValueError("No se pudo resolver la estrategia para el backtest runtime")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.backtesting",
        description="CLI del backtesting actual",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    runtime_parser = subparsers.add_parser("runtime", help="Ejecuta el backtest usado por la GUI")
    runtime_parser.add_argument("--strategy-key", default=str(getattr(config, "STRATEGY_KEY", "") or "").strip())
    runtime_parser.add_argument("--strategy-module", default=str(getattr(config, "STRATEGY_MODULE", "") or "").strip())
    runtime_parser.add_argument("--strategy-label", default="")
    runtime_parser.add_argument("--symbol", default=getattr(config, "SYMBOL", ""))
    runtime_parser.add_argument("--timeframe", default="")
    runtime_parser.add_argument("--start", required=True, help="Fecha inicio YYYY-MM-DD")
    runtime_parser.add_argument("--end", required=True, help="Fecha fin YYYY-MM-DD")
    runtime_parser.add_argument("--initial-balance", type=float, default=10000.0)
    runtime_parser.add_argument("--warmup-bars", type=int, default=0)
    runtime_parser.add_argument("--lot", type=float, default=float(getattr(config, "LOT", 0.01) or 0.01))
    runtime_parser.add_argument("--sl-points", type=float, default=float(getattr(config, "SL_POINTS", 0.0) or 0.0))
    runtime_parser.add_argument("--tp-points", type=float, default=float(getattr(config, "TP_POINTS", 0.0) or 0.0))
    runtime_parser.add_argument(
        "--data-source", default="mt5", choices=["mt5", "dukascopy"],
        help="Fuente de datos históricos. 'dukascopy' no requiere MT5.",
    )

    return parser


def _run_runtime(args) -> int:
    module_ref = _resolve_strategy_module_ref(args.strategy_key, args.strategy_module)
    module = _load_strategy_module(module_ref)

    raw_timeframe = args.timeframe or get_strategy_timeframe(module) or _default_timeframe_label()
    timeframe_value = resolve_timeframe_value(raw_timeframe)
    if timeframe_value is None:
        raise ValueError(f"Timeframe inválido: {raw_timeframe}")

    start_date = _parse_date(args.start, end_of_day=False)
    end_date = _parse_date(args.end, end_of_day=True)
    if end_date < start_date:
        raise ValueError("La fecha fin no puede ser anterior a la fecha inicio")

    request = {
        "strategy_key": str(args.strategy_key or "").strip() or "strategy",
        "strategy_label": str(args.strategy_label or args.strategy_key or module_ref).strip(),
        "module": module,
        "symbol": str(args.symbol or "").strip(),
        "timeframe_value": timeframe_value,
        "start_date": start_date,
        "end_date": end_date,
        "initial_balance": float(args.initial_balance),
        "lot": float(args.lot),
        "sl_points": float(args.sl_points),
        "tp_points": float(args.tp_points),
    }
    if int(args.warmup_bars or 0) > 0:
        request["warmup_bars"] = int(args.warmup_bars)

    data_source_name = str(getattr(args, "data_source", "mt5") or "mt5").strip().lower()

    if data_source_name == "mt5":
        if mt5 is None:
            print(
                "ERROR: MT5 no disponible. Usa --data-source dukascopy para backtesting sin MT5.",
                file=sys.stderr,
            )
            return 1
        mt5_connection.initialize_mt5()
        try:
            mt5_connection.check_symbol(request["symbol"])
            result = runtime.run_backtest(request)
        finally:
            mt5.shutdown()
    else:
        from backend.data.factory import build_data_source, resolve_symbol_for_request
        ds = build_data_source(data_source_name, request["symbol"])
        request["symbol"] = resolve_symbol_for_request(data_source_name, request["symbol"])
        result = runtime.run_backtest(request, data_source=ds)

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "success" else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "runtime":
        return _run_runtime(args)

    parser.error("Comando no soportado")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
