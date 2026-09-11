# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Motor de backtesting genérico alineado con el runtime actual.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from backend.core import config
from backend.data import data_feed
from backend.data.interface import IHistoricalDataSource
from backend.strategy.runtime import (
    TIMEFRAME_MAP,
    TIMEFRAME_MINUTES,
    apply_mtf_strategy_processing,
    apply_strategy_processing,
    build_timeframe_frames,
    get_strategy_signal_payload,
    get_strategy_signal_payload_mtf,
    get_strategy_timeframe,
    lowest_timeframe_label,
    resolve_timeframe_value,
    timeframe_label,
    timeframe_to_minutes,
)


_TIMEFRAME_STR_TO_MINUTES = dict(TIMEFRAME_MINUTES)


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
    return int(timeframe_to_minutes(timeframe_value, default=1))


def _default_warmup_bars() -> int:
    return max(int(getattr(config, "BARS_HISTORY", 500) or 500), 500)


def _build_market_dataframe(
    symbol: str,
    timeframe_value: int,
    start_date: datetime,
    end_date: datetime,
    warmup_bars: int,
    data_source: IHistoricalDataSource,
) -> pd.DataFrame:
    tf_label = timeframe_label(timeframe_value) or "M1"
    timeframe_minutes = _TIMEFRAME_STR_TO_MINUTES.get(tf_label, 1)
    warmup_minutes = max(1, warmup_bars) * timeframe_minutes
    warmup_start = start_date - timedelta(minutes=warmup_minutes)

    fetch_label = "M1" if tf_label in {"M2", "M3", "M10"} else tf_label
    df = data_source.get_rates_df(symbol, fetch_label, warmup_start, end_date)
    if df is None or df.empty:
        raise RuntimeError(f"No se pudieron obtener datos para {symbol} en el rango especificado")

    df = df.sort_values("time").reset_index(drop=True)
    if fetch_label != tf_label:
        from backend.strategy.runtime import resample_ohlcv
        df = resample_ohlcv(df, tf_label)
    df = data_feed.add_source_columns(df, config.SOURCE_MODE)
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
    spread_points: float = 0.0
    slippage_points: float = 0.0
    commission_per_lot: float = 0.0
    data_provider: str = "mt5"

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
            spread_points=float(raw.get("spread_points") or 0.0),
            slippage_points=float(raw.get("slippage_points") or 0.0),
            commission_per_lot=float(raw.get("commission_per_lot") or 0.0),
            data_provider=str(raw.get("data_provider") or "mt5"),
        )


class BacktestEngine:
    def __init__(self, request: BacktestRequest, data_source: IHistoricalDataSource):
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
        self._data_source = data_source

        instrument_info = data_source.get_instrument_info(self.symbol)
        if instrument_info is None:
            raise RuntimeError(f"No se pudo obtener información del símbolo {self.symbol}")
        self.point = instrument_info.point
        self.tick_size = instrument_info.tick_size
        self.tick_value = instrument_info.tick_value
        self.digits = int(getattr(instrument_info, "digits", 0) or 0)
        if self.tick_size <= 0 or self.tick_value <= 0:
            raise RuntimeError(f"Symbol {self.symbol} has invalid tick metadata")
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
        return (max(0.0, float(requested_lot or 0.0)), None)

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
                "direction": position["direction"],
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
        raw_fill = float(candle["open"])

        if current_direction == direction:
            return

        if current_direction != 0:
            self._close_all_positions(
                candle=candle,
                exit_price=raw_fill,
                reason="REVERSAL",
            )

        lot, volume_note = self._normalize_volume(self.request.lot)
        if lot <= 0:
            return

        cost_points = (self.request.spread_points + self.request.slippage_points) * self.point
        if direction == 1:
            entry_price = raw_fill + cost_points
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
            entry_price = raw_fill - cost_points
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

        self.balance -= self.request.commission_per_lot * lot

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

    def _open_advanced(self, candle: pd.Series, signal_payload: dict, direction: int) -> None:
        direction = 1 if int(direction or 1) >= 0 else -1
        atr_value = float(signal_payload.get("atr_value") or 0.0)
        if atr_value <= 0:
            return

        sl_atr_mult = float(signal_payload.get("sl_atr_mult") or 1.0)
        tp_atr_mult = float(signal_payload.get("tp_atr_mult") or 2.0)
        pyramid_atr_mult = float(signal_payload.get("pyramid_atr_mult") or 0.5)
        max_entries = signal_payload.get("max_entries")
        entry_index = signal_payload.get("entry_index")
        try:
            max_entries = int(max_entries) if max_entries is not None else None
        except (TypeError, ValueError):
            max_entries = None
        try:
            entry_index = int(entry_index) if entry_index is not None else None
        except (TypeError, ValueError):
            entry_index = None

        dynamic_sizing = bool(signal_payload.get("dynamic_sizing"))
        volume_ratio = float(signal_payload.get("volume_ratio") or 0.0)
        risk_pct = float(signal_payload.get("risk_pct") or 0.0)
        requested_lot = self.request.lot
        if risk_pct > 0 and sl_atr_mult > 0:
            risk_money = self.balance * risk_pct
            risk_per_lot = (atr_value * sl_atr_mult) * self.value_per_price_unit_per_lot
            requested_lot = risk_money / risk_per_lot if risk_per_lot > 0 else 0.0

        lot, volume_note = self._normalize_volume(requested_lot)
        if lot <= 0:
            return

        raw_fill = float(candle["open"])
        cost_points = (self.request.spread_points + self.request.slippage_points) * self.point
        entry_price = raw_fill + direction * cost_points

        if max_entries is not None and max_entries > 0 and len(self.open_positions) >= max_entries:
            return
        if entry_index is not None and entry_index >= 0 and len(self.open_positions) != entry_index:
            return

        if self.open_positions:
            most_recent = max(
                self.open_positions,
                key=lambda item: (_time_to_epoch(item["entry_time"]) or 0, item["id"]),
            )
            if most_recent["direction"] != direction:
                return
            # El umbral de piramidación avanza a favor de la posición.
            pyramid_threshold = float(most_recent["entry_price"]) + direction * (pyramid_atr_mult * atr_value)
            if direction == 1 and entry_price < pyramid_threshold:
                return
            if direction == -1 and entry_price > pyramid_threshold:
                return

        self.balance -= self.request.commission_per_lot * lot

        self._new_position(
            candle=candle,
            direction=direction,
            volume=lot,
            entry_price=entry_price,
            sl=entry_price - direction * (sl_atr_mult * atr_value),
            tp=entry_price + direction * (tp_atr_mult * atr_value),
            signal="buy" if direction == 1 else "sell",
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

        if signal in {"buy", "sell"} and pyramiding and atr_value > 0:
            self._open_advanced(candle, signal_payload, 1 if signal == "buy" else -1)
            return

        self._apply_standard_signal(candle, signal_payload)

    def _is_mtf_module(self) -> bool:
        return hasattr(self.module, "get_last_signal_payload_mtf") or hasattr(self.module, "prepare_frames")

    def _required_timeframes(self) -> list[str]:
        required = list(getattr(self.module, "REQUIRED_TIMEFRAMES", []) or [])
        primary = str(getattr(self.module, "PRIMARY_TIMEFRAME", getattr(self.module, "TIMEFRAME", self.timeframe_label)) or "").upper()
        if primary and primary not in required:
            required.append(primary)
        return required or [self.timeframe_label]

    @staticmethod
    def _slice_frames_until(frames: dict[str, pd.DataFrame], timestamp) -> dict[str, pd.DataFrame]:
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        sliced = {}
        for label, frame in frames.items():
            if frame is None or frame.empty or "time" not in frame.columns:
                sliced[label] = frame
                continue
            times = pd.to_datetime(frame["time"], utc=True)
            sliced[label] = frame.loc[times <= ts].copy().reset_index(drop=True)
        return sliced

    def _run_mtf_with_df(self, base_df: pd.DataFrame) -> dict:
        try:
            required = self._required_timeframes()
            base_label = lowest_timeframe_label(required)
            frames = build_timeframe_frames(base_df, required, base_timeframe=base_label)
            frames = apply_mtf_strategy_processing(
                frames,
                self.module,
                enable_signals=bool(getattr(config, "ENABLE_SIGNALS", True)),
            )
        except Exception as error:
            return {"status": "error", "error": str(error)}

        primary_label = str(getattr(self.module, "PRIMARY_TIMEFRAME", getattr(self.module, "TIMEFRAME", self.timeframe_label)) or self.timeframe_label).upper()
        strategy_df = frames.get(primary_label)
        if strategy_df is None or strategy_df.empty or "time" not in strategy_df.columns:
            return {"status": "error", "error": "La estrategia MTF no devolvió frame primario válido"}

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
            prefix_time = strategy_df.iloc[first_visible_index]["time"]
            try:
                pending_signal = get_strategy_signal_payload_mtf(
                    self._slice_frames_until(frames, prefix_time),
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

            prefix_time = strategy_df.iloc[next_index]["time"]
            try:
                pending_signal = get_strategy_signal_payload_mtf(
                    self._slice_frames_until(frames, prefix_time),
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

    def _build_success_result(self) -> dict:
        total_profit = self.balance - self.initial_balance
        closed_count = len(self.closed_trades)
        winning_trades = 0
        losing_trades = 0
        gross_wins = 0.0
        gross_losses = 0.0
        for t in self.closed_trades:
            p = t["profit"]
            if p > 0:
                winning_trades += 1
                gross_wins += p
            elif p < 0:
                losing_trades += 1
                gross_losses -= p
        win_rate = (winning_trades / closed_count * 100.0) if closed_count else 0.0

        profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0.0
        avg_win = gross_wins / winning_trades if winning_trades > 0 else 0.0
        avg_loss = gross_losses / losing_trades if losing_trades > 0 else 0.0
        loss_rate = losing_trades / closed_count if closed_count > 0 else 0.0
        expectancy = (win_rate / 100.0) * avg_win - loss_rate * avg_loss

        drawdown_curve = []
        running_peak = self.initial_balance
        for point in self.equity_curve:
            eq = point["equity"]
            if eq > running_peak:
                running_peak = eq
            dd_pct = ((running_peak - eq) / running_peak * 100.0) if running_peak > 0 else 0.0
            drawdown_curve.append({"time": point["time"], "drawdown_pct": round(dd_pct, 4)})

        return {
            "status": "success",
            "error": "",
            "strategy_key": self.request.strategy_key,
            "strategy_label": self.request.strategy_label,
            "symbol": self.symbol,
            "digits": self.digits,
            "timeframe": self.timeframe_label,
            "data_provider": self.request.data_provider,
            "start_date": _time_to_epoch(self.request.start_date),
            "end_date": _time_to_epoch(self.request.end_date),
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "total_profit": total_profit,
            "total_return_pct": (total_profit / self.initial_balance * 100.0),
            "closed_trades": closed_count,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "max_drawdown": self.max_drawdown,
            "profit_factor": round(profit_factor, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "expectancy": round(expectancy, 4),
            "cost_params": {
                "spread_points": self.request.spread_points,
                "slippage_points": self.request.slippage_points,
                "commission_per_lot": self.request.commission_per_lot,
            },
            "trades": self.closed_trades,
            "equity_curve": self.equity_curve,
            "drawdown_curve": drawdown_curve,
        }

    def run_with_df(self, base_df: pd.DataFrame) -> dict:
        if self._is_mtf_module():
            return self._run_mtf_with_df(base_df)

        try:
            strategy_df = apply_strategy_processing(
                base_df,
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

    def run(self) -> dict:
        original_timeframe_value = self.timeframe_value
        try:
            if self._is_mtf_module():
                fetch_label = lowest_timeframe_label(self._required_timeframes())
                self.timeframe_value = TIMEFRAME_MAP.get(fetch_label, self.timeframe_value)
            df = _build_market_dataframe(
                self.symbol,
                self.timeframe_value,
                self.request.start_date,
                self.request.end_date,
                self.request.warmup_bars,
                self._data_source,
            )
        except Exception as error:
            return {"status": "error", "error": str(error)}
        finally:
            self.timeframe_value = original_timeframe_value
        return self.run_with_df(df)


def run_backtest(request: dict, data_source: IHistoricalDataSource = None) -> dict:
    if data_source is None:
        from backend.data.mt5_historical_source import MT5HistoricalDataSource
        data_source = MT5HistoricalDataSource()
    engine = BacktestEngine(BacktestRequest.from_dict(request), data_source)
    return engine.run()


def _empty_metrics(initial_balance: float) -> dict:
    return {
        "initial_balance":  initial_balance,
        "final_balance":    initial_balance,
        "total_profit":     0.0,
        "total_return_pct": 0.0,
        "closed_trades":    0,
        "winning_trades":   0,
        "losing_trades":    0,
        "win_rate":         0.0,
        "max_drawdown":     0.0,
        "profit_factor":    0.0,
    }


def _make_error_entry(strat: dict, tf_label: str, initial_balance: float, error: str) -> dict:
    return {
        "status":         "error",
        "error":          error,
        "strategy_key":   str(strat.get("strategy_key") or ""),
        "strategy_label": str(strat.get("strategy_label") or strat.get("strategy_key") or ""),
        "timeframe":      tf_label,
        **_empty_metrics(initial_balance),
    }


def _extract_comparison_summary(result: dict, fallback_balance: float) -> dict:
    if result.get("status") != "success":
        return {
            "status":         "error",
            "error":          str(result.get("error") or ""),
            "strategy_key":   str(result.get("strategy_key") or ""),
            "strategy_label": str(result.get("strategy_label") or ""),
            "timeframe":      str(result.get("timeframe") or ""),
            **_empty_metrics(fallback_balance),
        }
    return {
        "status":           "success",
        "error":            "",
        "strategy_key":     result["strategy_key"],
        "strategy_label":   result["strategy_label"],
        "timeframe":        result["timeframe"],
        "initial_balance":  result["initial_balance"],
        "final_balance":    result["final_balance"],
        "total_profit":     result["total_profit"],
        "total_return_pct": result["total_return_pct"],
        "closed_trades":    result["closed_trades"],
        "winning_trades":   result["winning_trades"],
        "losing_trades":    result["losing_trades"],
        "win_rate":         result["win_rate"],
        "max_drawdown":     result["max_drawdown"],
        "profit_factor":    result["profit_factor"],
    }


def run_backtest_comparison(request: dict, data_source: IHistoricalDataSource = None) -> dict:
    if not isinstance(request, dict):
        return {"status": "error", "error": "El request debe ser un dict"}
    if data_source is None:
        from backend.data.mt5_historical_source import MT5HistoricalDataSource
        data_source = MT5HistoricalDataSource()

    symbol = str(request.get("symbol") or "").strip()
    if not symbol:
        return {"status": "error", "error": "Se requiere símbolo"}

    try:
        start_date = _as_utc_datetime(request["start_date"])
        end_date   = _as_utc_datetime(request["end_date"])
    except Exception as e:
        return {"status": "error", "error": f"Fechas inválidas: {e}"}

    if end_date < start_date:
        return {"status": "error", "error": "La fecha fin no puede ser anterior a la fecha inicio"}

    initial_balance = float(request.get("initial_balance") or 0.0)
    if initial_balance <= 0:
        return {"status": "error", "error": "El balance inicial debe ser mayor que cero"}

    strategies_raw = list(request.get("strategies") or [])
    if not strategies_raw:
        return {"status": "error", "error": "Se requiere al menos una estrategia"}

    warmup_bars = max(1, int(request.get("warmup_bars") or _default_warmup_bars()))
    lot         = float(request.get("lot") or getattr(config, "LOT", 0.01) or 0.01)
    sl_points   = float(request.get("sl_points") or getattr(config, "SL_POINTS", 0.0) or 0.0)
    tp_points   = float(request.get("tp_points") or getattr(config, "TP_POINTS", 0.0) or 0.0)

    default_tv = resolve_timeframe_value(request.get("timeframe")) or TIMEFRAME_MAP["M1"]

    # Group strategies by timeframe_value
    groups: dict = {}
    for i, strat in enumerate(strategies_raw):
        module = strat.get("module")
        if module is not None and (hasattr(module, "get_last_signal_payload_mtf") or hasattr(module, "prepare_frames")):
            required = list(getattr(module, "REQUIRED_TIMEFRAMES", []) or [])
            primary = str(getattr(module, "PRIMARY_TIMEFRAME", getattr(module, "TIMEFRAME", "")) or "").upper()
            if primary and primary not in required:
                required.append(primary)
            tv = TIMEFRAME_MAP.get(lowest_timeframe_label(required), default_tv)
        else:
            tv = int(strat.get("timeframe_value") or default_tv)
        if tv not in groups:
            groups[tv] = []
        groups[tv].append((i, strat))

    results_by_index: dict = {}

    for tv, indexed_strats in groups.items():
        try:
            base_df = _build_market_dataframe(symbol, tv, start_date, end_date, warmup_bars, data_source)
        except Exception as e:
            for idx, strat in indexed_strats:
                results_by_index[idx] = _make_error_entry(
                    strat,
                    timeframe_label(tv),
                    initial_balance,
                    f"Error descargando datos ({timeframe_label(tv)}): {e}",
                )
            continue

        for idx, strat in indexed_strats:
            module = strat.get("module")
            if module is None:
                results_by_index[idx] = _make_error_entry(
                    strat, timeframe_label(tv), initial_balance,
                    "La estrategia no tiene módulo cargado",
                )
                continue

            strat_request = BacktestRequest(
                strategy_key    = str(strat.get("strategy_key") or "strategy"),
                strategy_label  = str(strat.get("strategy_label") or strat.get("strategy_key") or "Strategy"),
                module          = module,
                symbol          = symbol,
                timeframe_value = tv,
                start_date      = start_date,
                end_date        = end_date,
                initial_balance = initial_balance,
                warmup_bars     = warmup_bars,
                lot             = lot,
                sl_points       = sl_points,
                tp_points       = tp_points,
            )

            try:
                engine = BacktestEngine(strat_request, data_source)
                individual = engine.run_with_df(base_df)
            except Exception as e:
                results_by_index[idx] = _make_error_entry(
                    strat, timeframe_label(tv), initial_balance, str(e)
                )
                continue

            results_by_index[idx] = _extract_comparison_summary(individual, initial_balance)

    results = [results_by_index[i] for i in range(len(strategies_raw))]

    success_count = sum(1 for r in results if r["status"] == "success")
    error_count   = sum(1 for r in results if r["status"] == "error")

    if success_count == 0:
        top_status = "error"
        top_error  = "; ".join(r["error"] for r in results if r.get("error"))
    elif error_count > 0:
        top_status = "partial"
        top_error  = f"{error_count} de {len(results)} estrategias fallaron"
    else:
        top_status = "success"
        top_error  = ""

    return {
        "status":          top_status,
        "error":           top_error,
        "symbol":          symbol,
        "start_date":      _time_to_epoch(start_date),
        "end_date":        _time_to_epoch(end_date),
        "initial_balance": initial_balance,
        "strategies":      results,
    }
