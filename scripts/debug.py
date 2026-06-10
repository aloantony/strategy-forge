"""
Debug runner — ejercita cualquier módulo del sistema desde terminal sin GUI.

Uso:
    python scripts/debug.py datasource --source dukascopy --symbol GER40 --tf H1 --days 3
    python scripts/debug.py datasource --source mt5 --symbol "#Germany40" --tf M5 --days 1
    python scripts/debug.py backtest --source dukascopy --symbol GER40 --tf H1 --strategy my_strategy --days 30
    python scripts/debug.py factory --symbol "#Germany40"
"""

import argparse
import sys
import os
from datetime import datetime, timedelta, timezone

# Asegura que el root del proyecto esté en el path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── helpers ──────────────────────────────────────────────────────────────────

def _now_utc():
    return datetime.now(tz=timezone.utc)


def _print_df(df, label="DataFrame"):
    print(f"\n-- {label} ({'vacio' if df.empty else f'{len(df)} filas'}) --")
    if df.empty:
        print("  (sin datos)")
        return
    print(f"  Columnas : {list(df.columns)}")
    print(f"  Dtypes   : {dict(df.dtypes)}")
    print(f"  Rango    : {df['time'].iloc[0]} -> {df['time'].iloc[-1]}")
    print(f"\n{df.head(3).to_string(index=False)}")
    print("  ...")
    print(f"{df.tail(3).to_string(index=False)}")


def _print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print("="*60)


# ── subcomandos ───────────────────────────────────────────────────────────────

def cmd_datasource(args):
    """Descarga OHLCV de la fuente indicada e imprime resultado."""
    from backend.data.factory import build_data_source, resolve_symbol_for_request

    end = _now_utc()
    start = end - timedelta(days=args.days)

    _print_section(f"datasource  source={args.source}  symbol={args.symbol}  tf={args.tf}  days={args.days}")
    print(f"  Rango   : {start.date()} -> {end.date()}")

    try:
        ds = build_data_source(args.source, args.symbol)
        request_symbol = resolve_symbol_for_request(args.source, args.symbol)
        print(f"  Instancia: {type(ds).__name__}")
        print(f"  Símbolo  : {request_symbol}")

        df = ds.get_rates_df(request_symbol, args.tf, start, end)
        _print_df(df, "OHLCV")

        info = ds.get_instrument_info(request_symbol)
        if info:
            print(f"\n-- InstrumentInfo --")
            for k, v in info.__dict__.items():
                print(f"  {k}: {v}")
    except Exception as e:
        import traceback
        print(f"\n  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)


def cmd_backtest(args):
    """Ejecuta un backtest completo e imprime métricas."""
    from backend.data.factory import build_data_source, resolve_symbol_for_request
    from backend.backtesting.runtime import run_backtest
    import importlib, config

    end = _now_utc()
    start = end - timedelta(days=args.days)

    _print_section(f"backtest  source={args.source}  symbol={args.symbol}  tf={args.tf}  strategy={args.strategy}  days={args.days}")

    try:
        ds = build_data_source(args.source, args.symbol)
        request_symbol = resolve_symbol_for_request(args.source, args.symbol)

        from backend.backtesting.runtime import resolve_timeframe_value
        module = importlib.import_module(f"strategies.{args.strategy}")

        request = {
            "strategy_key": args.strategy,
            "strategy_label": args.strategy,
            "module": module,
            "symbol": request_symbol,
            "timeframe_value": resolve_timeframe_value(args.tf),
            "start_date": start,
            "end_date": end,
            "initial_balance": float(args.balance),
            "warmup_bars": 500,
            "lot": float(getattr(config, "LOT", 0.01)),
            "sl_points": float(getattr(config, "SL_POINTS", 300)),
            "tp_points": float(getattr(config, "TP_POINTS", 500)),
        }

        result = run_backtest(request, data_source=ds)

        if result.get("status") not in ("ok", "success"):
            print(f"\n  STATUS: {result.get('status')}")
            print(f"  ERROR : {result.get('error', '(sin mensaje)')}")
            sys.exit(1)

        print(f"\n── Métricas ──")
        skip = {"equity_curve", "drawdown_curve", "trades"}
        for k, v in result.items():
            if k not in skip:
                print(f"  {k}: {v}")

        trades = result.get("trades") or []
        print(f"\n── Trades ({len(trades)}) ──")
        for t in trades[:5]:
            print(f"  {t}")
        if len(trades) > 5:
            print(f"  ... ({len(trades)-5} más)")

    except Exception as e:
        import traceback
        print(f"\n  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)


def cmd_factory(args):
    """Prueba la resolución de símbolo y disponibilidad de fuentes."""
    from backend.data.factory import resolve_canonical_symbol, resolve_symbol_for_request, build_data_source

    _print_section(f"factory  symbol={args.symbol}")

    canonical = resolve_canonical_symbol(args.symbol)
    print(f"  canonical      : {canonical}")
    print(f"  mt5 request    : {resolve_symbol_for_request('mt5', args.symbol)}")

    if canonical:
        try:
            resolve_symbol_for_request("dukascopy", args.symbol)
            print(f"  dukascopy req  : {resolve_symbol_for_request('dukascopy', args.symbol)}")
        except ValueError as e:
            print(f"  dukascopy req  : ERROR — {e}")

    for source in ("mt5", "dukascopy"):
        try:
            ds = build_data_source(source, args.symbol)
            print(f"  build({source:10}) : OK — {type(ds).__name__}")
        except Exception as e:
            print(f"  build({source:10}) : ERROR — {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Debug runner — ejercita módulos del sistema sin GUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # datasource
    p_ds = sub.add_parser("datasource", help="Descarga OHLCV y muestra schema + muestra")
    p_ds.add_argument("--source", default="dukascopy", choices=["mt5", "dukascopy"])
    p_ds.add_argument("--symbol", default="GER40")
    p_ds.add_argument("--tf", default="H1")
    p_ds.add_argument("--days", type=int, default=3)

    # backtest
    p_bt = sub.add_parser("backtest", help="Ejecuta un backtest completo")
    p_bt.add_argument("--source", default="dukascopy", choices=["mt5", "dukascopy"])
    p_bt.add_argument("--symbol", default="GER40")
    p_bt.add_argument("--tf", default="H1")
    p_bt.add_argument("--strategy", required=True, help="Nombre del módulo (sin 'strategy_' prefix)")
    p_bt.add_argument("--days", type=int, default=30)
    p_bt.add_argument("--balance", type=float, default=10000)

    # factory
    p_fac = sub.add_parser("factory", help="Prueba resolución de símbolo y disponibilidad de fuentes")
    p_fac.add_argument("--symbol", default="#Germany40")

    args = parser.parse_args()

    dispatch = {"datasource": cmd_datasource, "backtest": cmd_backtest, "factory": cmd_factory}
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
