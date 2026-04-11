"""
Motor de backtesting genérico alineado con el runtime actual.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import MetaTrader5 as mt5
import pandas as pd

import config
import data_feed
import trading
from strategy_runtime import (
    TIMEFRAME_MAP,
    apply_strategy_processing,
    get_strategy_signal_payload,
    get_strategy_timeframe,
    resolve_timeframe_value,
    timeframe_label,
)


TIMEFRAME_MINUTES = {
    mt5.TIMEFRAME_M1: 1,
    mt5.TIMEFRAME_M5: 5,
    mt5.TIMEFRAME_M15: 15,
    mt5.TIMEFRAME_M30: 30,
    mt5.TIMEFRAME_H1: 60,
    mt5.TIMEFRAME_H4: 240,
    mt5.TIMEFRAME_D1: 1440,
}


def _as_utc_datetime(value: Any) -> datetime:
    if isinstance(value, pd.Timestamp):
        dt = value.to_pydatetime()
    elif isinstance(value, datetime):
        dt = value
    else:
        raise TypeError(f"Fecha inválida para backtest: {value!r}")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _time_to_epoch(value) -> int | None:
    if value is None:
        return None
    dt = _as_utc_datetime(value)
    return int(dt.timestamp())


def _timeframe_to_minutes(timeframe_value: int) -> int:
    return int(TIMEFRAME_MINUTES.get(timeframe_value, 1))


def _default_warmup_bars() -> int:
    return max(int(getattr(config, "BARS_HISTORY", 500) or 500), 500)


def _build_market_dataframe(
    symbol: str,
    timeframe_value: int,
    start_date: datetime,
    end_date: datetime,
    warmup_bars: int,
) -> pd.DataFrame:
    timeframe_minutes = _timeframe_to_minutes(timeframe_value)
    warmup_minutes = max(1, warmup_bars) * timeframe_minutes
    warmup_start = start_date - timedelta(minutes=warmup_minutes)

    rates = mt5.copy_rates_range(symbol, timeframe_value, warmup_start, end_date)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No se pudieron obtener datos para {symbol} en el rango especificado")

    df = pd.DataFrame(rates)
    if df.empty:
        raise RuntimeError(f"No se recibieron velas para {symbol}")

    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.sort_values("time").reset_index(drop=True)
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


@dataclass
class BacktestRequest:
    strategy_key: str
    strategy_label: str
    module: Any
    symbol: str
    timeframe_value: int
    start_date: datetime
    end_date: datetime
    initial_balance: float
    warmup_bars: int
    lot: float
    sl_points: float
    tp_points: float

    @classmethod
    def from_dict(cls, raw: dict) -> "BacktestRequest":
        if not isinstance(raw, dict):
            raise TypeError("El request del backtest debe ser un dict")

        module = raw.get("module")
        if module is None:
            raise ValueError("El request del backtest requiere 'module'")

        timeframe_value = raw.get("timeframe_value")
        if timeframe_value is None:
            timeframe_value = resolve_timeframe_value(raw.get("timeframe"))
        if timeframe_value is None:
            timeframe_value = resolve_timeframe_value(get_strategy_timeframe(module))
        if timeframe_value is None:
            timeframe_value = resolve_timeframe_value(getattr(config, "TIMEFRAME", None))
        if timeframe_value is None:
            timeframe_value = TIMEFRAME_MAP["M1"]

        initial_balance = float(raw.get("initial_balance", 0.0) or 0.0)
        if initial_balance <= 0:
            raise ValueError("El balance inicial debe ser mayor que cero")

        start_date = _as_utc_datetime(raw.get("start_date"))
        end_date = _as_utc_datetime(raw.get("end_date"))
        if end_date < start_date:
            raise ValueError("La fecha fin no puede ser anterior a la fecha inicio")

        return cls(
            strategy_key=str(raw.get("strategy_key") or "").strip() or "strategy",
            strategy_label=str(raw.get("strategy_label") or raw.get("strategy_key") or "Strategy").strip(),
            module=module,
            symbol=str(raw.get("symbol") or getattr(config, "SYMBOL", "") or "").strip(),
            timeframe_value=int(timeframe_value),
            start_date=start_date,
            end_date=end_date,
            initial_balance=initial_balance,
            warmup_bars=max(1, int(raw.get("warmup_bars") or _default_warmup_bars())),
            lot=float(raw.get("lot") or getattr(config, "LOT", 0.01) or 0.01),
            sl_points=float(raw.get("sl_points") or getattr(config, "SL_POINTS", 0.0) or 0.0),
            tp_points=float(raw.get("tp_points") or getattr(config, "TP_POINTS", 0.0) or 0.0),
        )


class BacktestEngine:
    def __init__(self, request: BacktestRequest):
        self.request = request
        self.symbol = request.symbol
        self.module = request.module
        self.timeframe_value = request.timeframe_value
        self.timeframe_label = timeframe_label(request.timeframe_value) or "M1"
        self.initial_balance = request.initial_balance
        self.balance = request.initial_balance
        self.open_positions: list[dict] = []
        self.closed_trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.max_drawdown = 0.0
        self.peak_equity = request.initial_balance
        self._position_seq = 0

        self.symbol_info = mt5.symbol_info(self.symbol)
        if self.symbol_info is None:
            raise RuntimeError(f"No se pudo obtener información del símbolo {self.symbol}")

        self.point = float(getattr(self.symbol_info, "point", 0.0) or 0.0)
        self.tick_size = float(getattr(self.symbol_info, "trade_tick_size", 0.0) or 0.0)
        self.tick_value = float(getattr(self.symbol_info, "trade_tick_value", 0.0) or 0.0)
        if self.point <= 0:
            self.point = self.tick_size
        if self.tick_size <= 0 or self.tick_value <= 0:
            raise RuntimeError(
                f"El símbolo {self.symbol} no expone trade_tick_size/trade_tick_value válidos"
            )
        self.value_per_price_unit_per_lot = self.tick_value / self.tick_size

    def _current_direction(self) -> int:
        if not self.open_positions:
            return 0
        return int(self.open_positions[0].get("direction") or 0)

    def _calculate_profit(
        self,
        entry_price: float,
        exit_price: float,
        direction: int,
        volume: float,
    ) -> float:
        return (
            (float(exit_price) - float(entry_price))
            * int(direction)
            * float(volume)
            * self.value_per_price_unit_per_lot
        )

    def _update_drawdown(self, equity: float) -> None:
        if equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity <= 0:
            return
        drawdown = ((self.peak_equity - equity) / self.peak_equity) * 100.0
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def _mark_equity(self, candle: pd.Series) -> None:
        close_price = float(candle["close"])
        floating = 0.0
        for position in self.open_positions:
            floating += self._calculate_profit(
                position["entry_price"],
                close_price,
                position["direction"],
                position["volume"],
            )
        equity = self.balance + floating
        self._update_drawdown(equity)
        self.equity_curve.append(
            {
                "time": _time_to_epoch(candle["time"]),
                "equity": equity,
                "balance": self.balance,
            }
        )

    def _normalize_volume(self, requested_lot: float) -> tuple[float, str | None]:
        return trading.normalize_volume(float(requested_lot or 0.0), self.symbol_info)

    def _new_position(
        self,
        *,
        candle: pd.Series,
        direction: int,
        volume: float,
        entry_price: float,
        sl: float,
        tp: float,
        signal: str,
        signal_reason: str,
        mode: str,
        atr_value: float = 0.0,
        volume_ratio: float = 0.0,
        dynamic_sizing: bool = False,
        volume_note: str | None = None,
    ) -> None:
        self._position_seq += 1
        self.open_positions.append(
            {
                "id": self._position_seq,
                "entry_time": candle["time"],
                "entry_price": float(entry_price),
                "direction": int(direction),
                "type": "BUY" if direction == 1 else "SELL",
                "volume": float(volume),
                "sl": float(sl) if sl else 0.0,
                "tp": float(tp) if tp else 0.0,
                "signal": signal,
                "signal_reason": signal_reason,
                "mode": mode,
                "atr_value": float(atr_value or 0.0),
                "volume_ratio": float(volume_ratio or 0.0),
                "dynamic_sizing": bool(dynamic_sizing),
                "volume_note": volume_note,
            }
        )

    def _close_position(
        self,
        position: dict,
        *,
        candle_time,
        exit_price: float,
        reason: str,
        forced: bool = False,
    ) -> None:
        profit = self._calculate_profit(
            position["entry_price"],
            exit_price,
            position["direction"],
            position["volume"],
        )
        self.balance += profit
        self.closed_trades.append(
            {
                "id": position["id"],
                "entry_time": _time_to_epoch(position["entry_time"]),
                "exit_time": _time_to_epoch(candle_time),
                "time": _time_to_epoch(candle_time),
                "direction": position["type"],
                "entry_price": position["entry_price"],
                "exit_price": float(exit_price),
                "price": float(exit_price),
                "volume": position["volume"],
                "profit": profit,
                "reason": reason,
                "forced_close": bool(forced),
                "signal": position["signal"],
                "signal_reason": position["signal_reason"],
                "mode": position["mode"],
                "volume_note": position.get("volume_note"),
            }
        )
        self.open_positions = [
            item for item in self.open_positions if item["id"] != position["id"]
        ]

    def _close_all_positions(
        self,
        *,
        candle: pd.Series,
        exit_price: float,
        reason: str,
        forced: bool = False,
    ) -> None:
        for position in list(self.open_positions):
            self._close_position(
                position,
                candle_time=candle["time"],
                exit_price=exit_price,
                reason=reason,
                forced=forced,
            )

    def _check_sl_tp_hit(self, candle: pd.Series, position: dict) -> tuple[bool, str, float]:
        high = float(candle["high"])
        low = float(candle["low"])
        sl = float(position.get("sl") or 0.0)
        tp = float(position.get("tp") or 0.0)

        if position["direction"] == 1:
            if sl > 0 and low <= sl:
                return True, "SL", sl
            if tp > 0 and high >= tp:
                return True, "TP", tp
        else:
            if sl > 0 and high >= sl:
                return True, "SL", sl
            if tp > 0 and low <= tp:
                return True, "TP", tp

        return False, "", 0.0

    def _process_candle_exits(self, candle: pd.Series) -> None:
        for position in list(self.open_positions):
            hit, reason, exit_price = self._check_sl_tp_hit(candle, position)
            if hit:
                self._close_position(
                    position,
                    candle_time=candle["time"],
                    exit_price=exit_price,
                    reason=reason,
                )

    def _apply_standard_signal(self, candle: pd.Series, signal_payload: dict) -> None:
        signal = signal_payload.get("signal", "none")
        if signal not in {"buy", "sell"}:
            return

        direction = 1 if signal == "buy" else -1
        current_direction = self._current_direction()
        entry_price = float(candle["open"])

        if current_direction == direction:
            return

        if current_direction != 0:
            self._close_all_positions(
                candle=candle,
                exit_price=entry_price,
                reason="REVERSAL",
            )

        lot, volume_note = self._normalize_volume(self.request.lot)
        if lot <= 0:
            return

        if direction == 1:
            sl = (
                entry_price - (self.request.sl_points * self.point)
                if self.request.sl_points > 0
                else 0.0
            )
            tp = (
                entry_price + (self.request.tp_points * self.point)
                if self.request.tp_points > 0
                else 0.0
            )
        else:
            sl = (
                entry_price + (self.request.sl_points * self.point)
                if self.request.sl_points > 0
                else 0.0
            )
            tp = (
                entry_price - (self.request.tp_points * self.point)
                if self.request.tp_points > 0
                else 0.0
            )

        self._new_position(
            candle=candle,
            direction=direction,
            volume=lot,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            signal=signal,
            signal_reason=str(signal_payload.get("reason") or ""),
            mode="standard",
            volume_note=volume_note,
        )

    def _open_advanced_buy(self, candle: pd.Series, signal_payload: dict) -> None:
        atr_value = float(signal_payload.get("atr_value") or 0.0)
        if atr_value <= 0:
            return

        dynamic_sizing = bool(signal_payload.get("dynamic_sizing"))
        volume_ratio = float(signal_payload.get("volume_ratio") or 0.0)
        if dynamic_sizing and volume_ratio > 0:
            raw_lot = trading.calculate_dynamic_lot(
                self.symbol,
                atr_value,
                volume_ratio,
                balance=self.balance,
            )
            requested_lot = raw_lot if raw_lot > 0 else self.request.lot
        else:
            requested_lot = self.request.lot

        lot, volume_note = self._normalize_volume(requested_lot)
        if lot <= 0:
            return

        entry_price = float(candle["open"])
        open_positions = [
            {
                "type": position["type"],
                "volume": position["volume"],
                "price_open": position["entry_price"],
                "price_current": float(candle["close"]),
                "profit": self._calculate_profit(
                    position["entry_price"],
                    float(candle["close"]),
                    position["direction"],
                    position["volume"],
                ),
                "sl": position["sl"],
                "tp": position["tp"],
                "time_open": _time_to_epoch(position["entry_time"]),
            }
            for position in self.open_positions
        ]

        if open_positions:
            most_recent = max(
                self.open_positions,
                key=lambda item: (_time_to_epoch(item["entry_time"]) or 0, item["id"]),
            )
            if most_recent["direction"] != 1:
                return
            pyramid_threshold = float(most_recent["entry_price"]) + (0.5 * atr_value)
            if entry_price < pyramid_threshold:
                return

        allowed, _aggregate_risk_pct = trading.check_aggregate_risk(
            self.symbol,
            lot,
            atr_value,
            self.balance,
            open_positions,
        )
        if not allowed:
            return

        self._new_position(
            candle=candle,
            direction=1,
            volume=lot,
            entry_price=entry_price,
            sl=entry_price - atr_value,
            tp=entry_price + (2.0 * atr_value),
            signal="buy",
            signal_reason=str(signal_payload.get("reason") or ""),
            mode="advanced",
            atr_value=atr_value,
            volume_ratio=volume_ratio,
            dynamic_sizing=dynamic_sizing,
            volume_note=volume_note,
        )

    def _apply_pending_signal(self, candle: pd.Series, signal_payload: dict) -> None:
        if not isinstance(signal_payload, dict):
            return

        signal = signal_payload.get("signal", "none")
        pyramiding = bool(signal_payload.get("pyramiding"))
        atr_value = float(signal_payload.get("atr_value") or 0.0)

        if signal == "buy" and pyramiding and atr_value > 0:
            self._open_advanced_buy(candle, signal_payload)
            return

        self._apply_standard_signal(candle, signal_payload)

    def _build_success_result(self) -> dict:
        total_profit = self.balance - self.initial_balance
        closed_trades = len(self.closed_trades)
        winning_trades = sum(1 for trade in self.closed_trades if trade["profit"] > 0)
        losing_trades = sum(1 for trade in self.closed_trades if trade["profit"] < 0)
        win_rate = ((winning_trades / closed_trades) * 100.0) if closed_trades else 0.0

        return {
            "status": "success",
            "error": "",
            "strategy_key": self.request.strategy_key,
            "strategy_label": self.request.strategy_label,
            "symbol": self.symbol,
            "timeframe": self.timeframe_label,
            "start_date": _time_to_epoch(self.request.start_date),
            "end_date": _time_to_epoch(self.request.end_date),
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "total_profit": total_profit,
            "total_return_pct": (
                ((self.balance - self.initial_balance) / self.initial_balance) * 100.0
            ),
            "closed_trades": closed_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "max_drawdown": self.max_drawdown,
            "trades": self.closed_trades,
        }

    def run(self) -> dict:
        try:
            df = _build_market_dataframe(
                self.symbol,
                self.timeframe_value,
                self.request.start_date,
                self.request.end_date,
                self.request.warmup_bars,
            )
            strategy_df = apply_strategy_processing(
                df,
                self.module,
                enable_signals=bool(getattr(config, "ENABLE_SIGNALS", True)),
            )
        except Exception as error:
            return {"status": "error", "error": str(error)}

        if strategy_df is None or strategy_df.empty or "time" not in strategy_df.columns:
            return {
                "status": "error",
                "error": "La estrategia no devolvió datos válidos para backtest",
            }

        strategy_df = strategy_df.sort_values("time").reset_index(drop=True)
        time_series = pd.to_datetime(strategy_df["time"], utc=True)
        visible_mask = (
            (time_series >= pd.Timestamp(self.request.start_date))
            & (time_series <= pd.Timestamp(self.request.end_date))
        )
        visible_indices = strategy_df.index[visible_mask].tolist()
        if not visible_indices:
            return {"status": "error", "error": "No hay velas dentro del rango solicitado"}

        last_visible_index = int(visible_indices[-1])
        first_visible_index = int(visible_indices[0])
        pending_signal = None

        if first_visible_index > 0:
            prefix_df = strategy_df.iloc[: first_visible_index + 1]
            try:
                pending_signal = get_strategy_signal_payload(
                    prefix_df,
                    self.module,
                    verbose=False,
                )
            except Exception as error:
                return {"status": "error", "error": str(error)}

        for idx in visible_indices:
            candle = strategy_df.iloc[int(idx)]
            if pending_signal is not None:
                self._apply_pending_signal(candle, pending_signal)
                pending_signal = None

            self._process_candle_exits(candle)
            self._mark_equity(candle)

            next_index = int(idx) + 1
            if next_index > last_visible_index:
                continue

            prefix_df = strategy_df.iloc[: next_index + 1]
            try:
                pending_signal = get_strategy_signal_payload(
                    prefix_df,
                    self.module,
                    verbose=False,
                )
            except Exception as error:
                return {"status": "error", "error": str(error)}

        last_candle = strategy_df.iloc[last_visible_index]
        if self.open_positions:
            self._close_all_positions(
                candle=last_candle,
                exit_price=float(last_candle["close"]),
                reason="END_OF_RANGE",
                forced=True,
            )
            self._mark_equity(last_candle)

        return self._build_success_result()


def run_backtest(request: dict) -> dict:
    engine = BacktestEngine(BacktestRequest.from_dict(request))
    return engine.run()
