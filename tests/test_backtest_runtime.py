# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Optional

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.backtesting import runtime as backtest_runtime
from backend.strategy import runtime as strategy_runtime
from backend.brokers.interface import InstrumentInfo


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class _MockDataSource:
    """IHistoricalDataSource mock for tests — no MT5 required."""

    def get_rates_df(self, symbol, timeframe, start, end):
        raise RuntimeError("get_rates_df should not be called (monkeypatched _build_market_dataframe)")

    def get_instrument_info(self, symbol) -> Optional[InstrumentInfo]:
        return InstrumentInfo(
            symbol=symbol,
            tick_size=1.0,
            tick_value=1.0,
            point=1.0,
            digits=0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            volume_digits=2,
            trade_stops_level=0,
            trade_freeze_level=0,
            trade_fillings=1,
            filling_mode=1,
            trade_exemode=0,
        )


def test_normalize_signal_payload_supports_runtime_extras():
    payload = strategy_runtime.normalize_signal_payload(
        {
            "signal": "BUY",
            "reason": "x" * 200,
            "pyramiding": 1,
            "atr_value": "2.5",
            "dynamic_sizing": True,
            "volume_ratio": "1.4",
        }
    )

    assert payload["signal"] == "buy"
    assert payload["pyramiding"] is True
    assert payload["dynamic_sizing"] is True
    assert payload["atr_value"] == pytest.approx(2.5)
    assert payload["volume_ratio"] == pytest.approx(1.4)
    assert len(payload["reason"]) <= 160


def test_backtest_standard_mode_reverses_and_closes_at_end_of_range(monkeypatch):
    df = pd.DataFrame(
        [
            {"time": _utc(2026, 4, 1, 9, 0), "open": 90.0, "high": 92.0, "low": 89.0, "close": 91.0, "planned_signal": "none"},
            {"time": _utc(2026, 4, 1, 9, 1), "open": 95.0, "high": 99.0, "low": 94.0, "close": 99.0, "planned_signal": "buy"},
            {"time": _utc(2026, 4, 1, 9, 2), "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0, "planned_signal": "sell"},
            {"time": _utc(2026, 4, 1, 9, 3), "open": 102.0, "high": 103.0, "low": 95.0, "close": 96.0, "planned_signal": "none"},
        ]
    )

    class StrategyModule:
        TIMEFRAME = "M1"

        @staticmethod
        def get_last_signal(local_df, verbose=False):
            return local_df.iloc[-2]["planned_signal"]

    monkeypatch.setattr(backtest_runtime, "_build_market_dataframe", lambda *args, **kwargs: df.copy())

    result = backtest_runtime.run_backtest(
        {
            "strategy_key": "std",
            "strategy_label": "Standard",
            "module": StrategyModule,
            "symbol": "TEST",
            "timeframe_value": backtest_runtime.TIMEFRAME_MAP["M1"],
            "start_date": _utc(2026, 4, 1, 9, 2),
            "end_date": _utc(2026, 4, 1, 9, 3),
            "initial_balance": 1000.0,
            "warmup_bars": 10,
            "lot": 1.0,
            "sl_points": 5.0,
            "tp_points": 10.0,
        },
        data_source=_MockDataSource(),
    )

    assert result["status"] == "success"
    assert result["closed_trades"] == 2
    assert result["winning_trades"] == 2
    assert result["losing_trades"] == 0
    assert result["final_balance"] == pytest.approx(1008.0)
    assert result["total_profit"] == pytest.approx(8.0)
    assert [trade["reason"] for trade in result["trades"]] == ["REVERSAL", "END_OF_RANGE"]
    assert [trade["direction"] for trade in result["trades"]] == [1, -1]
    assert result["trades"][0]["entry_price"] == pytest.approx(100.0)
    assert result["trades"][0]["exit_price"] == pytest.approx(102.0)
    assert result["trades"][1]["entry_price"] == pytest.approx(102.0)
    assert result["trades"][1]["exit_price"] == pytest.approx(96.0)


def test_backtest_advanced_mode_supports_pyramiding(monkeypatch):
    df = pd.DataFrame(
        [
            {"time": _utc(2026, 4, 1, 9, 0), "open": 99.0, "high": 99.5, "low": 98.5, "close": 99.0, "payload_signal": "none", "atr_value_col": 1.0, "volume_ratio_col": 1.5},
            {"time": _utc(2026, 4, 1, 9, 1), "open": 99.4, "high": 99.8, "low": 99.2, "close": 99.6, "payload_signal": "buy", "atr_value_col": 1.0, "volume_ratio_col": 1.5},
            {"time": _utc(2026, 4, 1, 9, 2), "open": 100.0, "high": 100.8, "low": 99.5, "close": 100.4, "payload_signal": "buy", "atr_value_col": 1.0, "volume_ratio_col": 1.5},
            {"time": _utc(2026, 4, 1, 9, 3), "open": 100.6, "high": 101.4, "low": 100.2, "close": 101.0, "payload_signal": "none", "atr_value_col": 1.0, "volume_ratio_col": 1.5},
            {"time": _utc(2026, 4, 1, 9, 4), "open": 101.0, "high": 101.8, "low": 100.7, "close": 101.6, "payload_signal": "none", "atr_value_col": 1.0, "volume_ratio_col": 1.5},
        ]
    )

    class StrategyModule:
        TIMEFRAME = "M1"

        @staticmethod
        def get_last_signal_payload(local_df, verbose=False):
            row = local_df.iloc[-2]
            return {
                "signal": row["payload_signal"],
                "reason": f"signal:{row['payload_signal']}",
                "pyramiding": True,
                "atr_value": row["atr_value_col"],
                "dynamic_sizing": True,
                "volume_ratio": row["volume_ratio_col"],
            }

    monkeypatch.setattr(backtest_runtime, "_build_market_dataframe", lambda *args, **kwargs: df.copy())

    result = backtest_runtime.run_backtest(
        {
            "strategy_key": "adv",
            "strategy_label": "Advanced",
            "module": StrategyModule,
            "symbol": "TEST",
            "timeframe_value": backtest_runtime.TIMEFRAME_MAP["M1"],
            "start_date": _utc(2026, 4, 1, 9, 2),
            "end_date": _utc(2026, 4, 1, 9, 4),
            "initial_balance": 1000.0,
            "warmup_bars": 10,
            "lot": 0.1,
            "sl_points": 5.0,
            "tp_points": 10.0,
        },
        data_source=_MockDataSource(),
    )

    assert result["status"] == "success"
    assert result["closed_trades"] == 2
    assert result["winning_trades"] == 2
    # Two pyramiding positions closed at END_OF_RANGE at close=101.6
    # Position 1: entry=100.0, profit=(101.6-100.0)*1*0.1*1.0=0.16
    # Position 2: entry=100.6, profit=(101.6-100.6)*1*0.1*1.0=0.10
    assert result["final_balance"] == pytest.approx(1000.26)
    assert result["total_profit"] == pytest.approx(0.26)
    assert [trade["mode"] for trade in result["trades"]] == ["advanced", "advanced"]
    assert [trade["reason"] for trade in result["trades"]] == ["END_OF_RANGE", "END_OF_RANGE"]
    assert [trade["entry_price"] for trade in result["trades"]] == pytest.approx([100.0, 100.6])
    assert [trade["volume"] for trade in result["trades"]] == pytest.approx([0.1, 0.1])


def test_backtest_advanced_short_pyramiding(monkeypatch):
    """Cortos avanzados: SL/TP en ATRs invertidos y piramidación hacia abajo."""
    df = pd.DataFrame(
        [
            {"time": _utc(2026, 4, 1, 9, 0), "open": 101.0, "high": 101.2, "low": 100.8, "close": 101.0, "payload_signal": "none"},
            {"time": _utc(2026, 4, 1, 9, 1), "open": 100.6, "high": 100.8, "low": 100.2, "close": 100.4, "payload_signal": "sell"},
            {"time": _utc(2026, 4, 1, 9, 2), "open": 100.0, "high": 100.2, "low": 99.5, "close": 99.6, "payload_signal": "sell"},
            {"time": _utc(2026, 4, 1, 9, 3), "open": 99.4, "high": 99.6, "low": 99.0, "close": 99.0, "payload_signal": "none"},
            {"time": _utc(2026, 4, 1, 9, 4), "open": 99.0, "high": 99.2, "low": 98.3, "close": 98.4, "payload_signal": "none"},
        ]
    )

    class StrategyModule:
        TIMEFRAME = "M1"

        @staticmethod
        def get_last_signal_payload(local_df, verbose=False):
            row = local_df.iloc[-2]
            return {
                "signal": row["payload_signal"],
                "reason": f"signal:{row['payload_signal']}",
                "pyramiding": True,
                "atr_value": 1.0,
            }

    monkeypatch.setattr(backtest_runtime, "_build_market_dataframe", lambda *args, **kwargs: df.copy())

    result = backtest_runtime.run_backtest(
        {
            "strategy_key": "adv_short",
            "strategy_label": "Advanced Short",
            "module": StrategyModule,
            "symbol": "TEST",
            "timeframe_value": backtest_runtime.TIMEFRAME_MAP["M1"],
            "start_date": _utc(2026, 4, 1, 9, 2),
            "end_date": _utc(2026, 4, 1, 9, 4),
            "initial_balance": 1000.0,
            "warmup_bars": 10,
            "lot": 0.1,
            "sl_points": 5.0,
            "tp_points": 10.0,
        },
        data_source=_MockDataSource(),
    )

    assert result["status"] == "success"
    assert result["closed_trades"] == 2
    assert [trade["direction"] for trade in result["trades"]] == [-1, -1]
    assert [trade["mode"] for trade in result["trades"]] == ["advanced", "advanced"]
    # Entradas: 100.0 (inicial) y 99.4 (piramidada por debajo del umbral 99.5)
    assert [trade["entry_price"] for trade in result["trades"]] == pytest.approx([100.0, 99.4])
    # Cerradas a fin de rango con close=98.4 → (100.0-98.4)*0.1 + (99.4-98.4)*0.1
    assert result["final_balance"] == pytest.approx(1000.26)
    assert result["winning_trades"] == 2


def test_backtest_incomplete_pyramiding_payload_falls_back_to_standard(monkeypatch):
    df = pd.DataFrame(
        [
            {"time": _utc(2026, 4, 1, 9, 0), "open": 99.0, "high": 99.0, "low": 99.0, "close": 99.0, "planned_signal": "none"},
            {"time": _utc(2026, 4, 1, 9, 1), "open": 99.0, "high": 99.5, "low": 98.8, "close": 99.2, "planned_signal": "buy"},
            {"time": _utc(2026, 4, 1, 9, 2), "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "planned_signal": "none"},
        ]
    )

    class StrategyModule:
        TIMEFRAME = "M1"

        @staticmethod
        def get_last_signal_payload(local_df, verbose=False):
            row = local_df.iloc[-2]
            return {
                "signal": row["planned_signal"],
                "reason": "fallback-standard",
                "pyramiding": True,
                "atr_value": 0.0,
                "dynamic_sizing": True,
                "volume_ratio": 1.2,
            }

    monkeypatch.setattr(backtest_runtime, "_build_market_dataframe", lambda *args, **kwargs: df.copy())

    result = backtest_runtime.run_backtest(
        {
            "strategy_key": "fallback",
            "strategy_label": "Fallback",
            "module": StrategyModule,
            "symbol": "TEST",
            "timeframe_value": backtest_runtime.TIMEFRAME_MAP["M1"],
            "start_date": _utc(2026, 4, 1, 9, 2),
            "end_date": _utc(2026, 4, 1, 9, 2),
            "initial_balance": 1000.0,
            "warmup_bars": 10,
            "lot": 1.0,
            "sl_points": 5.0,
            "tp_points": 10.0,
        },
        data_source=_MockDataSource(),
    )

    assert result["status"] == "success"
    assert result["closed_trades"] == 1
    assert result["trades"][0]["mode"] == "standard"
    assert result["trades"][0]["entry_price"] == pytest.approx(100.0)
    assert result["trades"][0]["exit_price"] == pytest.approx(100.5)


def test_backtest_mtf_mode_uses_required_frames_and_advanced_payload(monkeypatch):
    df = pd.DataFrame(
        [
            {"time": _utc(2026, 4, 1, 9, 0), "open": 99.0, "high": 99.5, "low": 98.5, "close": 99.0},
            {"time": _utc(2026, 4, 1, 9, 1), "open": 99.5, "high": 100.0, "low": 99.0, "close": 99.7},
            {"time": _utc(2026, 4, 1, 9, 2), "open": 100.0, "high": 100.6, "low": 99.8, "close": 100.4},
            {"time": _utc(2026, 4, 1, 9, 3), "open": 100.7, "high": 101.2, "low": 100.3, "close": 101.0},
            {"time": _utc(2026, 4, 1, 9, 4), "open": 101.3, "high": 101.8, "low": 100.9, "close": 101.6},
        ]
    )

    class StrategyModule:
        TIMEFRAME = "M1"
        PRIMARY_TIMEFRAME = "M1"
        REQUIRED_TIMEFRAMES = ["M1", "M2"]

        @staticmethod
        def prepare_frames(frames):
            return frames

        @staticmethod
        def get_last_signal_payload_mtf(frames, verbose=False):
            m1 = frames["M1"]
            m2 = frames["M2"]
            if len(m2) < 2:
                return {"signal": "none"}
            planned = {2: 0, 3: 1}.get(len(m1) - 1)
            if planned is None:
                return {"signal": "none"}
            return {
                "signal": "buy",
                "reason": f"mtf-tier-{planned}",
                "pyramiding": True,
                "atr_value": 1.0,
                "sl_atr_mult": 1.5,
                "tp_atr_mult": 20.0,
                "pyramid_atr_mult": 0.5,
                "entry_index": planned,
                "max_entries": 2,
                "risk_pct": 0.0,
                "block_id": "A",
                "tier_id": f"tier_{planned + 1}",
            }

    monkeypatch.setattr(backtest_runtime, "_build_market_dataframe", lambda *args, **kwargs: df.copy())

    result = backtest_runtime.run_backtest(
        {
            "strategy_key": "mtf",
            "strategy_label": "MTF",
            "module": StrategyModule,
            "symbol": "TEST",
            "timeframe_value": backtest_runtime.TIMEFRAME_MAP["M5"],
            "start_date": _utc(2026, 4, 1, 9, 2),
            "end_date": _utc(2026, 4, 1, 9, 4),
            "initial_balance": 1000.0,
            "warmup_bars": 10,
            "lot": 0.1,
            "sl_points": 5.0,
            "tp_points": 10.0,
        },
        data_source=_MockDataSource(),
    )

    assert result["status"] == "success"
    assert result["timeframe"] == "M5"
    assert result["closed_trades"] == 2
    assert [trade["mode"] for trade in result["trades"]] == ["advanced", "advanced"]
    assert [trade["signal_reason"] for trade in result["trades"]] == ["mtf-tier-0", "mtf-tier-1"]
    assert [trade["entry_price"] for trade in result["trades"]] == pytest.approx([100.0, 100.7])
    assert [trade["exit_price"] for trade in result["trades"]] == pytest.approx([101.6, 101.6])
    assert result["final_balance"] == pytest.approx(1000.25)
