# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

from __future__ import annotations

from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.backtesting import cli


def test_cli_runtime_command_routes_to_runtime_runner(monkeypatch, capsys):
    captured = {}
    fake_module = types.ModuleType("fake_strategy")
    fake_module.TIMEFRAME = "M5"

    monkeypatch.setattr(cli.mt5_connection, "initialize_mt5", lambda: True)
    monkeypatch.setattr(cli.mt5_connection, "check_symbol", lambda symbol: True)
    monkeypatch.setattr(cli.mt5, "shutdown", lambda: True)
    monkeypatch.setattr(cli, "_load_strategy_module", lambda ref: fake_module)

    def _runtime_run_backtest(request: dict) -> dict:
        captured.update(request)
        return {"status": "success", "final_balance": 10123.45}

    monkeypatch.setattr(cli.runtime, "run_backtest", _runtime_run_backtest)

    exit_code = cli.main(
        [
            "runtime",
            "--strategy-key",
            "primera_estrategia",
            "--strategy-module",
            "strategies.strategy_primera_estrategia",
            "--strategy-label",
            "Primera Estrategia",
            "--symbol",
            "TEST",
            "--start",
            "2026-04-01",
            "--end",
            "2026-04-03",
            "--initial-balance",
            "15000",
            "--warmup-bars",
            "750",
            "--lot",
            "0.3",
            "--sl-points",
            "120",
            "--tp-points",
            "250",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert captured["strategy_key"] == "primera_estrategia"
    assert captured["strategy_label"] == "Primera Estrategia"
    assert captured["module"] is fake_module
    assert captured["symbol"] == "TEST"
    assert captured["timeframe_value"] == cli.resolve_timeframe_value("M5")
    assert captured["initial_balance"] == 15000.0
    assert captured["warmup_bars"] == 750
    assert captured["lot"] == 0.3
    assert captured["sl_points"] == 120.0
    assert captured["tp_points"] == 250.0
    assert '"status": "success"' in output
