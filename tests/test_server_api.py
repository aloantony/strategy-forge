# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
tests/test_server_api.py — Tests de la API del servidor (FastAPI + broker paper).

No requiere MT5: usa create_app(broker_name="paper").
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from server.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(broker_name="paper"))


def test_health():
    with _client() as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["broker"] == "PaperBrokerAdapter"
    print("PASS test_health")


def test_list_strategies():
    with _client() as client:
        r = client.get("/api/strategies")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list) and items, "deberia haber estrategias en strategies/"
        keys = {i["key"] for i in items}
        assert "strategy_primera_estrategia" in keys
        first = next(i for i in items if i["key"] == "strategy_primera_estrategia")
        assert first["has_config"] is True
        assert first["magic_number"] == 42501
    print("PASS test_list_strategies")


def test_enable_disable_strategy():
    with _client() as client:
        r = client.post("/api/strategies/strategy_primera_estrategia/enable")
        assert r.status_code == 200
        assert "strategy_primera_estrategia" in r.json()["active_strategies"]
        r = client.post("/api/strategies/strategy_primera_estrategia/disable")
        assert r.status_code == 200
        assert "strategy_primera_estrategia" not in r.json()["active_strategies"]
        r = client.post("/api/strategies/no_existe/enable")
        assert r.status_code == 404
    print("PASS test_enable_disable_strategy")


def test_account_and_positions_paper():
    with _client() as client:
        r = client.get("/api/account")
        assert r.status_code == 200
        assert r.json()["balance"] > 0
        r = client.get("/api/positions", params={"symbol": "TEST", "magic": 1})
        assert r.status_code == 200
        assert r.json()["positions"] == []
        r = client.get("/api/market-status", params={"symbol": "TEST"})
        assert r.status_code == 200
        assert r.json()["open"] is True
    print("PASS test_account_and_positions_paper")


def test_backtest_validation_errors():
    with _client() as client:
        r = client.post("/api/backtest/run", json={
            "strategy_key": "no_existe", "symbol": "X",
            "start_date": "2026-01-01", "end_date": "2026-01-02",
        })
        assert r.status_code == 404
        r = client.post("/api/backtest/run", json={
            "strategy_key": "strategy_primera_estrategia", "symbol": "X",
            "start_date": "2026-02-01", "end_date": "2026-01-01",  # fin < inicio
        })
        assert r.status_code == 400
    print("PASS test_backtest_validation_errors")


def test_ws_stream_snapshot():
    with _client() as client:
        with client.websocket_connect("/ws/stream?symbol=TEST&magic=1") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert msg["account"]["balance"] > 0
            assert msg["market"]["open"] is True
            assert isinstance(msg["positions"], list)
    print("PASS test_ws_stream_snapshot")


if __name__ == "__main__":
    test_health()
    test_list_strategies()
    test_enable_disable_strategy()
    test_account_and_positions_paper()
    test_backtest_validation_errors()
    test_ws_stream_snapshot()
    print("\nAll tests passed.")
