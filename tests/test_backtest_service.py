from __future__ import annotations

from datetime import timezone
import types

import pytest

from src.application.backtest_service import BacktestService


class DummyConfig:
    BARS_HISTORY = 250
    LOT = 0.2
    SL_POINTS = 120.0
    TP_POINTS = 240.0


def _service(calls: dict) -> BacktestService:
    def data_source_factory(source_name, symbol):
        calls["data_source_factory"] = (source_name, symbol)
        return {"source": source_name, "symbol": symbol}

    def symbol_resolver(source_name, symbol):
        calls["symbol_resolver"] = (source_name, symbol)
        return "GER40" if source_name == "dukascopy" else symbol

    def run_backtest_func(request, data_source=None):
        calls["run_backtest"] = (request, data_source)
        return {"status": "success", "final_balance": 101.0}

    def run_comparison_func(request, data_source=None):
        calls["run_comparison"] = (request, data_source)
        return {"status": "success", "results": []}

    return BacktestService(
        config_module=DummyConfig,
        data_source_factory=data_source_factory,
        symbol_resolver=symbol_resolver,
        run_backtest_func=run_backtest_func,
        run_comparison_func=run_comparison_func,
        local_tz=timezone.utc,
    )


def _entry(key="alpha"):
    return {
        "key": key,
        "label": key.title(),
        "module_obj": types.ModuleType(f"{key}_module"),
        "timeframe_value": 1,
    }


def test_prepare_run_builds_runtime_request_and_form():
    calls = {}
    service = _service(calls)

    prepared = service.prepare_run(
        {
            "strategy_key": "alpha",
            "symbol": "#Germany40",
            "preset": "1M",
            "start_date": "2026-04-01",
            "end_date": "2026-04-02",
            "initial_balance": "10000",
            "data_source": "dukascopy",
        },
        _entry("alpha"),
    )

    assert calls["data_source_factory"] == ("dukascopy", "#Germany40")
    assert calls["symbol_resolver"] == ("dukascopy", "#Germany40")
    assert prepared.form == {
        "strategy_key": "alpha",
        "symbol": "#Germany40",
        "preset": "1M",
        "start_date": "2026-04-01",
        "end_date": "2026-04-02",
        "initial_balance": "10000.00",
        "data_source": "dukascopy",
    }
    assert prepared.request["symbol"] == "GER40"
    assert prepared.request["strategy_key"] == "alpha"
    assert prepared.request["module"] is not None
    assert prepared.request["warmup_bars"] == 500
    assert prepared.request["lot"] == 0.2
    assert prepared.request["sl_points"] == 120.0
    assert prepared.request["tp_points"] == 240.0


def test_prepare_run_rejects_invalid_balance_and_dates():
    service = _service({})

    with pytest.raises(ValueError, match="balance inicial"):
        service.prepare_run(
            {
                "symbol": "#Germany40",
                "start_date": "2026-04-01",
                "end_date": "2026-04-02",
                "initial_balance": "0",
            },
            _entry(),
        )

    with pytest.raises(ValueError, match="fecha fin"):
        service.prepare_run(
            {
                "symbol": "#Germany40",
                "start_date": "2026-04-03",
                "end_date": "2026-04-02",
                "initial_balance": "10000",
            },
            _entry(),
        )


def test_prepare_comparison_builds_strategy_list():
    calls = {}
    service = _service(calls)

    prepared = service.prepare_comparison(
        {
            "symbol": "#Germany40",
            "start_date": "2026-04-01",
            "end_date": "2026-04-02",
            "initial_balance": "10000",
            "data_source": "mt5",
        },
        [_entry("alpha"), _entry("beta")],
    )

    assert prepared.request["symbol"] == "#Germany40"
    assert prepared.request["data_provider"] == "mt5"
    assert [item["strategy_key"] for item in prepared.request["strategies"]] == ["alpha", "beta"]
    assert calls["data_source_factory"] == ("mt5", "#Germany40")


def test_execute_methods_normalize_exceptions():
    def raises(*args, **kwargs):
        raise RuntimeError("boom")

    service = BacktestService(
        run_backtest_func=raises,
        run_comparison_func=raises,
    )

    assert service.execute_run({}) == {"status": "error", "error": "boom"}
    assert service.execute_comparison({}) == {"status": "error", "error": "boom"}

