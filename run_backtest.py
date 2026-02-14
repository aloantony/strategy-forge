"""
Script para ejecutar backtesting de la estrategia.
"""

from datetime import datetime, timedelta

import MetaTrader5 as mt5
import pandas as pd

import backtest
import config
import data_feed
import mt5_connection


def _parse_config_date(raw_value: str):
    # Para peques: convierte texto de fecha de config a datetime.
    text = (raw_value or "").strip()
    if not text:
        return None
    try:
        ts = pd.to_datetime(text, utc=True)
        return ts.to_pydatetime()
    except Exception as e:
        raise Exception(f"Fecha invalida en config: '{raw_value}' ({e})")


def _resolve_period():
    # Para peques: decide el rango del backtest segun config y origen de datos.
    start_cfg = _parse_config_date(getattr(config, "BACKTEST_START_DATE", ""))
    end_cfg = _parse_config_date(getattr(config, "BACKTEST_END_DATE", ""))
    if start_cfg and end_cfg:
        if start_cfg > end_cfg:
            raise Exception("BACKTEST_START_DATE no puede ser mayor que BACKTEST_END_DATE")
        return start_cfg, end_cfg

    data_source = (getattr(config, "BACKTEST_DATA_SOURCE", "csv") or "csv").lower()
    if data_source == "csv":
        csv_map = dict(getattr(config, "BACKTEST_CSV_COLUMN_MAP", {}) or {})
        if not csv_map.get("datetime"):
            csv_map["datetime"] = getattr(config, "BACKTEST_CSV_TIME_COL", "datetime")
        df = data_feed.get_rates_df_from_csv(
            path=getattr(config, "BACKTEST_CSV_PATH", ""),
            column_map=csv_map,
            timezone=getattr(config, "BACKTEST_CSV_TIMEZONE", "UTC"),
        )
        start_date = start_cfg or df["time"].iloc[0].to_pydatetime()
        end_date = end_cfg or df["time"].iloc[-1].to_pydatetime()
        if start_date > end_date:
            raise Exception("Rango de fechas invalido para CSV")
        return start_date, end_date

    # Comportamiento legacy para MT5: ultimos 30 dias.
    end_date = end_cfg or datetime.now()
    start_date = start_cfg or (end_date - timedelta(days=30))
    if start_date > end_date:
        raise Exception("Rango de fechas invalido")
    return start_date, end_date


def main():
    # Para peques: arranca todo el proceso de backtesting.
    if config.TIMEFRAME is None:
        config.TIMEFRAME = mt5.TIMEFRAME_M1

    data_source = (getattr(config, "BACKTEST_DATA_SOURCE", "csv") or "csv").lower()
    spec_source = (getattr(config, "BACKTEST_SYMBOL_SPEC_SOURCE", "config") or "config").lower()
    needs_mt5 = data_source == "mt5" or spec_source == "mt5"

    mt5_initialized = False
    if needs_mt5:
        try:
            mt5_connection.initialize_mt5()
            mt5_connection.check_symbol(config.SYMBOL)
            mt5_initialized = True
        except Exception as e:
            print(f"Error al inicializar MT5: {e}")
            return

    try:
        start_date, end_date = _resolve_period()
    except Exception as e:
        print(f"Error al resolver periodo: {e}")
        if mt5_initialized:
            mt5.shutdown()
        return

    print("\n" + "=" * 80)
    print("CONFIGURACION DEL BACKTEST")
    print("=" * 80)
    config.print_config()
    print(f"\nOrigen de datos: {data_source}")
    print(f"Origen de spec simbolo: {spec_source}")
    print("\nPeriodo de backtesting:")
    print(f"   Desde: {start_date.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Hasta: {end_date.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    try:
        csv_map = dict(getattr(config, "BACKTEST_CSV_COLUMN_MAP", {}) or {})
        if not csv_map.get("datetime"):
            csv_map["datetime"] = getattr(config, "BACKTEST_CSV_TIME_COL", "datetime")
        engine = backtest.run_backtest(
            symbol=config.SYMBOL,
            timeframe=config.TIMEFRAME,
            start_date=start_date,
            end_date=end_date,
            data_source=data_source,
            symbol_spec_source=spec_source,
            csv_path=getattr(config, "BACKTEST_CSV_PATH", ""),
            csv_column_map=csv_map,
            csv_timezone=getattr(config, "BACKTEST_CSV_TIMEZONE", "UTC"),
        )

        results = engine.get_results()
        if "positions" in results and len(results["positions"]) > 0:
            print("\nPRIMERAS 10 OPERACIONES:")
            print("-" * 80)
            for i, pos in enumerate(results["positions"][:10], 1):
                direction_str = "BUY" if pos["direction"] == 1 else "SELL"
                profit_str = f"+{pos['profit']:.2f}" if pos["profit"] >= 0 else f"{pos['profit']:.2f}"
                print(
                    f"{i}. {direction_str} | Entrada: {pos['entry_price']:.2f} | "
                    f"Salida: {pos['exit_price']:.2f} | Profit: {profit_str} | "
                    f"Razon: {pos['reason']}"
                )
            if len(results["positions"]) > 10:
                print(f"... y {len(results['positions']) - 10} operaciones mas")
            print("-" * 80)

    except Exception as e:
        print(f"\nError durante el backtesting: {e}")
        import traceback

        traceback.print_exc()
    finally:
        if mt5_initialized:
            mt5.shutdown()


if __name__ == "__main__":
    main()
