"""
Modulo de backtesting para la estrategia de trading.
Simula operaciones con datos historicos y calcula metricas de rendimiento.
"""

from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd

import config
import data_feed
from strategies import strategy_baseline


def resolve_symbol_spec(symbol: str, spec_source: str = None) -> dict:
    # Para peques: obtiene los parametros del simbolo para calcular ganancias.
    source = (spec_source or getattr(config, "BACKTEST_SYMBOL_SPEC_SOURCE", "config")).lower()
    if source == "config":
        point = float(getattr(config, "BACKTEST_POINT", 0.0) or 0.0)
        contract_size = float(getattr(config, "BACKTEST_CONTRACT_SIZE", 0.0) or 0.0)
        tick_value = float(getattr(config, "BACKTEST_TICK_VALUE", 0.0) or 0.0)
        if point <= 0 or contract_size <= 0 or tick_value <= 0:
            raise Exception(
                "BACKTEST_POINT, BACKTEST_CONTRACT_SIZE y BACKTEST_TICK_VALUE "
                "deben ser mayores que 0 cuando BACKTEST_SYMBOL_SPEC_SOURCE='config'"
            )
        return {
            "point": point,
            "contract_size": contract_size,
            "tick_value": tick_value,
        }

    if source == "mt5":
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise Exception(f"Simbolo {symbol} no encontrado en MT5")
        point = float(getattr(symbol_info, "point", 0.0) or 0.0)
        contract_size = float(getattr(symbol_info, "trade_contract_size", 0.0) or 0.0)
        tick_value = float(getattr(symbol_info, "trade_tick_value", 0.0) or 0.0)
        if point <= 0 or contract_size <= 0 or tick_value <= 0:
            raise Exception(f"Especificacion invalida para {symbol} en MT5")
        return {
            "point": point,
            "contract_size": contract_size,
            "tick_value": tick_value,
        }

    raise ValueError(f"BACKTEST_SYMBOL_SPEC_SOURCE no valido: {source}")


def load_backtest_dataframe(
    symbol: str,
    timeframe,
    start_date: datetime,
    end_date: datetime,
    source: str = None,
    csv_path: str = None,
    csv_column_map: dict = None,
    csv_timezone: str = None,
) -> pd.DataFrame:
    # Para peques: carga velas desde MT5 o CSV segun configuracion.
    data_source = (source or getattr(config, "BACKTEST_DATA_SOURCE", "csv")).lower()

    if data_source == "mt5":
        rates = mt5.copy_rates_range(symbol, timeframe, start_date, end_date)
        if rates is None or len(rates) == 0:
            raise Exception(f"No se pudieron obtener datos para {symbol} en el rango especificado")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    if data_source == "csv":
        path = csv_path or getattr(config, "BACKTEST_CSV_PATH", "")
        if not path:
            raise Exception("BACKTEST_CSV_PATH no esta configurado")
        map_cfg = dict(csv_column_map or getattr(config, "BACKTEST_CSV_COLUMN_MAP", {}) or {})
        if not map_cfg.get("datetime"):
            map_cfg["datetime"] = getattr(config, "BACKTEST_CSV_TIME_COL", "datetime")
        tz_cfg = csv_timezone or getattr(config, "BACKTEST_CSV_TIMEZONE", "UTC")
        return data_feed.get_rates_df_from_csv(
            path=path,
            column_map=map_cfg,
            timezone=tz_cfg,
            start_date=start_date,
            end_date=end_date,
        )

    raise ValueError(f"BACKTEST_DATA_SOURCE no valido: {data_source}")


class BacktestEngine:
    # Para peques: esta clase simula operaciones pasadas para ver como habria ido la estrategia.
    """
    Motor de backtesting que simula operaciones con datos historicos.
    """

    def __init__(
        self,
        symbol: str,
        timeframe,
        lot: float,
        sl_points: float,
        tp_points: float,
        symbol_spec: dict = None,
    ):
        # Para peques: prepara todo al inicio.
        self.symbol = symbol
        self.timeframe = timeframe
        self.lot = lot
        self.sl_points = sl_points
        self.tp_points = tp_points

        # Estado de la simulacion
        self.positions = []
        self.current_position = None
        self.equity_curve = []
        self.initial_balance = 10000.0
        self.balance = self.initial_balance

        # Metricas
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0.0
        self.max_drawdown = 0.0
        self.peak_equity = self.initial_balance

        spec = symbol_spec or resolve_symbol_spec(symbol)
        self.point = float(spec["point"])
        self.contract_size = float(spec["contract_size"])
        self.tick_value = float(spec["tick_value"])
        if self.point <= 0 or self.contract_size <= 0 or self.tick_value <= 0:
            raise Exception("La especificacion del simbolo es invalida")

    def calculate_profit(self, entry_price: float, exit_price: float, direction: int, volume: float) -> float:
        # Para peques: calcula ganancia/perdida de una operacion.
        price_diff = (exit_price - entry_price) * direction
        profit = price_diff * volume * self.contract_size / self.point * self.tick_value
        return profit

    def check_sl_tp(self, candle: pd.Series, position: dict) -> tuple[bool, str, float]:
        # Para peques: revisa si el precio toco SL o TP.
        entry_price = position["entry_price"]
        direction = position["direction"]
        sl = position["sl"]
        tp = position["tp"]

        if direction == 1:  # BUY
            if tp > 0 and candle["high"] >= tp:
                return True, "TP", tp
            if sl > 0 and candle["low"] <= sl:
                return True, "SL", sl
        else:  # SELL
            if tp > 0 and candle["low"] <= tp:
                return True, "TP", tp
            if sl > 0 and candle["high"] >= sl:
                return True, "SL", sl

        return False, "", 0.0

    def open_position(self, candle: pd.Series, direction: int, signal_type: str):
        # Para peques: abre una posicion con SL/TP.
        if self.current_position and self.current_position["direction"] != direction:
            self.close_position(candle, "REVERSAL")

        if self.current_position and self.current_position["direction"] == direction:
            return

        entry_price = candle["close"]
        if direction == 1:
            sl = entry_price - (self.sl_points * self.point) if self.sl_points > 0 else 0
            tp = entry_price + (self.tp_points * self.point) if self.tp_points > 0 else 0
        else:
            sl = entry_price + (self.sl_points * self.point) if self.sl_points > 0 else 0
            tp = entry_price - (self.tp_points * self.point) if self.tp_points > 0 else 0

        self.current_position = {
            "entry_time": candle["time"],
            "entry_price": entry_price,
            "direction": direction,
            "volume": self.lot,
            "sl": sl,
            "tp": tp,
            "signal_type": signal_type,
        }

    def close_position(self, candle: pd.Series, reason: str):
        # Para peques: cierra la posicion y actualiza metricas.
        if self.current_position is None:
            return

        exit_price = candle["close"]
        sl_tp_hit, sl_tp_reason, sl_tp_price = self.check_sl_tp(candle, self.current_position)
        if sl_tp_hit:
            exit_price = sl_tp_price
            reason = sl_tp_reason

        profit = self.calculate_profit(
            self.current_position["entry_price"],
            exit_price,
            self.current_position["direction"],
            self.current_position["volume"],
        )

        closed_position = {
            **self.current_position,
            "exit_time": candle["time"],
            "exit_price": exit_price,
            "profit": profit,
            "reason": reason,
        }
        self.positions.append(closed_position)

        self.balance += profit
        self.total_trades += 1
        self.total_profit += profit
        if profit > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        self.equity_curve.append(
            {
                "time": candle["time"],
                "balance": self.balance,
                "profit": profit,
            }
        )

        if self.balance > self.peak_equity:
            self.peak_equity = self.balance
        drawdown = ((self.peak_equity - self.balance) / self.peak_equity) * 100
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        self.current_position = None

    def run(self, df: pd.DataFrame, start_date: datetime, end_date: datetime):
        # Para peques: ejecuta la simulacion sobre un DataFrame ya cargado.
        print(f"\n{'='*80}")
        print("INICIANDO BACKTEST")
        print(f"{'='*80}")
        print(f"Simbolo: {self.symbol}")
        print(f"Periodo: {start_date.strftime('%Y-%m-%d')} a {end_date.strftime('%Y-%m-%d')}")
        print(f"Lote: {self.lot}")
        print(f"SL: {self.sl_points} puntos | TP: {self.tp_points} puntos")
        print(f"{'='*80}\n")

        if df is None or df.empty:
            raise Exception("No hay datos para ejecutar el backtest")

        print(f"✓ {len(df)} velas obtenidas\n")

        print("Procesando datos...")
        df = data_feed.add_source_columns(df, config.SOURCE_MODE)
        df = data_feed.add_baseline_bands(df, config.MA_LENGTH, config.ATR_LENGTH, config.ATR_MULT)
        df = strategy_baseline.compute_dir1_and_signals(df, config.ENABLE_SIGNALS)
        print("✓ Datos procesados\n")

        print("Simulando operaciones...")
        for i in range(len(df)):
            candle = df.iloc[i]

            if pd.isna(candle.get("upper")) or pd.isna(candle.get("lower")):
                continue

            if i > 0:
                prev_candle = df.iloc[i - 1]
                if prev_candle["up_sig"]:
                    self.open_position(candle, 1, "BUY")
                if prev_candle["dn_sig"]:
                    self.open_position(candle, -1, "SELL")

            if self.current_position:
                sl_tp_hit, reason, _ = self.check_sl_tp(candle, self.current_position)
                if sl_tp_hit:
                    self.close_position(candle, reason)

            if not self.current_position:
                self.equity_curve.append(
                    {
                        "time": candle["time"],
                        "balance": self.balance,
                        "profit": 0.0,
                    }
                )

        if self.current_position:
            last_candle = df.iloc[-1]
            self.close_position(last_candle, "END_OF_DATA")

        print("✓ Simulacion completada\n")

    def get_results(self) -> dict:
        # Para peques: devuelve metricas del backtest.
        if self.total_trades == 0:
            return {"total_trades": 0, "message": "No se ejecutaron operaciones en el periodo"}

        win_rate = (self.winning_trades / self.total_trades) * 100
        avg_win = (
            sum(p["profit"] for p in self.positions if p["profit"] > 0) / self.winning_trades
            if self.winning_trades > 0
            else 0
        )
        avg_loss = (
            sum(p["profit"] for p in self.positions if p["profit"] < 0) / self.losing_trades
            if self.losing_trades > 0
            else 0
        )
        profit_factor = (
            abs(avg_win * self.winning_trades / (avg_loss * self.losing_trades))
            if avg_loss != 0 and self.losing_trades > 0
            else 0
        )
        final_balance = self.balance
        total_return = ((final_balance - self.initial_balance) / self.initial_balance) * 100

        return {
            "initial_balance": self.initial_balance,
            "final_balance": final_balance,
            "total_profit": self.total_profit,
            "total_return_pct": total_return,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": self.max_drawdown,
            "positions": self.positions,
        }

    def print_results(self):
        # Para peques: imprime resultados de forma legible.
        results = self.get_results()

        if "message" in results:
            print(results["message"])
            return

        print(f"\n{'='*80}")
        print("RESULTADOS DEL BACKTEST")
        print(f"{'='*80}\n")

        print("BALANCE:")
        print(f"   Inicial: {results['initial_balance']:.2f}")
        print(f"   Final: {results['final_balance']:.2f}")
        print(f"   Profit Total: {results['total_profit']:.2f} ({results['total_return_pct']:+.2f}%)\n")

        print("OPERACIONES:")
        print(f"   Total: {results['total_trades']}")
        print(f"   Ganadoras: {results['winning_trades']} ({results['win_rate']:.2f}%)")
        print(f"   Perdedoras: {results['losing_trades']} ({100 - results['win_rate']:.2f}%)\n")

        print("METRICAS:")
        print(f"   Ganancia promedio: {results['avg_win']:.2f}")
        print(f"   Perdida promedio: {results['avg_loss']:.2f}")
        print(f"   Profit Factor: {results['profit_factor']:.2f}")
        print(f"   Max Drawdown: {results['max_drawdown']:.2f}%\n")

        closes_by_reason = {}
        for pos in results["positions"]:
            reason = pos["reason"]
            if reason not in closes_by_reason:
                closes_by_reason[reason] = {"count": 0, "profit": 0.0}
            closes_by_reason[reason]["count"] += 1
            closes_by_reason[reason]["profit"] += pos["profit"]

        print("CIERRES POR RAZON:")
        for reason, data in closes_by_reason.items():
            print(f"   {reason}: {data['count']} operaciones, Profit: {data['profit']:.2f}")

        print(f"\n{'='*80}\n")


def run_backtest(
    symbol: str,
    timeframe,
    start_date: datetime,
    end_date: datetime,
    lot: float = None,
    sl_points: float = None,
    tp_points: float = None,
    data_source: str = None,
    symbol_spec_source: str = None,
    csv_path: str = None,
    csv_column_map: dict = None,
    csv_timezone: str = None,
):
    # Para peques: lanza una prueba y devuelve el motor con resultados.
    df = load_backtest_dataframe(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        source=data_source,
        csv_path=csv_path,
        csv_column_map=csv_column_map,
        csv_timezone=csv_timezone,
    )
    symbol_spec = resolve_symbol_spec(symbol=symbol, spec_source=symbol_spec_source)

    engine = BacktestEngine(
        symbol=symbol,
        timeframe=timeframe,
        lot=lot or config.LOT,
        sl_points=sl_points or config.SL_POINTS,
        tp_points=tp_points or config.TP_POINTS,
        symbol_spec=symbol_spec,
    )

    engine.run(df=df, start_date=start_date, end_date=end_date)
    engine.print_results()
    return engine
