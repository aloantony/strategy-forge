# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
tests/test_server_builder.py — API REST del Strategy Builder (server/routers/builder.py).

Usa el broker paper y redirige strategies/ a un tmp_path vía config.STRATEGY_DIR.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from backend.core import config as core_config
from server.app import create_app


V1_CONFIG = {
    "display_name": "Web RSI Test",
    "description": "RSI bajo con cierre sobre la EMA.",
    "timeframe": "M5",
    "indicators": [
        {"id": "RSI", "params": {"period": 14}, "columns": ["rsi_14"], "pre_computed": False},
        {"id": "EMA", "params": {"period": 50}, "columns": ["ema_50"], "pre_computed": False},
    ],
    "buy_condition": {
        "type": "AND",
        "children": [
            {"type": "condition", "left": "rsi_14", "op": "<", "right": 30},
            {"type": "condition", "left": "close", "op": ">", "right": "ema_50"},
        ],
    },
    "sell_condition": {"type": "condition", "left": "rsi_14", "op": ">", "right": 70},
}

MTF_CONFIG = {
    "mode": "multi_timeframe",
    "display_name": "Web MTF Test",
    "primary_timeframe": "H1",
    "indicators": [],
    "blocks": [
        {
            "id": "main",
            "trigger_timeframe": "H1",
            "confirm_timeframes": ["H4"],
            "risk_tiers": [0.01, 0.005],
        }
    ],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core_config, "STRATEGY_DIR", str(tmp_path))
    monkeypatch.setattr(core_config, "ACTIVE_STRATEGIES", [])
    with TestClient(create_app(broker_name="paper")) as c:
        c.strategies_dir = tmp_path
        yield c


def _import_strategy(py_path: Path):
    spec = importlib.util.spec_from_file_location("_srv_builder_test", py_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_builder_meta(client):
    meta = client.get("/api/builder/meta").json()
    ids = {ind["id"] for ind in meta["indicators"]}
    assert {"EMA", "RSI", "BB", "VORTEX", "SUPERTREND"} <= ids
    assert all(ind["label"] for ind in meta["indicators"])
    assert {o["op"] for o in meta["operators"]} == {"<", ">", "<=", ">=", "==", "!="}
    assert "H1" in meta["timeframes"]
    assert any(c["column"] == "close" for c in meta["base_columns"])
    mtf_ids = set(meta["mtf"]["indicator_ids"])
    assert {"ATR", "VORTEX", "EMA", "RSI", "BB"} <= mtf_ids
    assert not ({"HMA", "SUPERTREND", "TCI"} & mtf_ids)  # pre-computados: no en MTF
    assert meta["mtf"]["rules_mode"] is True
    assert meta["max_group_depth"] == 4


def test_create_v1_strategy(client):
    r = client.post("/api/builder/strategies", json=V1_CONFIG)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["key"] == "strategy_web_rsi_test"
    assert 10000 <= body["magic_number"] <= 99999

    py_path = client.strategies_dir / "strategy_web_rsi_test.py"
    assert py_path.is_file()
    assert (client.strategies_dir / "strategy_web_rsi_test.json").is_file()
    mod = _import_strategy(py_path)
    assert callable(mod.get_last_signal)
    assert mod.TIMEFRAME == "M5"

    # Aparece en el catálogo general con has_config
    items = client.get("/api/strategies").json()
    entry = next(e for e in items if e["key"] == "strategy_web_rsi_test")
    assert entry["has_config"] is True


def test_create_duplicate_rejected_409(client):
    assert client.post("/api/builder/strategies", json=V1_CONFIG).status_code == 201
    r = client.post("/api/builder/strategies", json=V1_CONFIG)
    assert r.status_code == 409
    assert "web_rsi_test" in r.json()["detail"]


def test_edit_preserves_magic_and_renames(client):
    created = client.post("/api/builder/strategies", json=V1_CONFIG).json()
    magic = created["magic_number"]

    edited = dict(V1_CONFIG)
    edited["display_name"] = "Web RSI Renombrada"
    edited["timeframe"] = "M15"
    r = client.put("/api/builder/strategies/strategy_web_rsi_test", json=edited)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"] == "strategy_web_rsi_renombrada"
    assert body["magic_number"] == magic
    assert body["timeframe"] == "M15"
    # rename limpia los ficheros antiguos
    assert not (client.strategies_dir / "strategy_web_rsi_test.py").exists()
    assert not (client.strategies_dir / "strategy_web_rsi_test.json").exists()


def test_edit_missing_returns_404(client):
    r = client.put("/api/builder/strategies/strategy_no_existe", json=V1_CONFIG)
    assert r.status_code == 404


def test_get_config_and_404(client):
    client.post("/api/builder/strategies", json=V1_CONFIG)
    cfg = client.get("/api/builder/strategies/strategy_web_rsi_test").json()
    assert cfg["display_name"] == "Web RSI Test"
    assert cfg["buy_condition"]["type"] == "AND"
    assert client.get("/api/builder/strategies/strategy_nada").status_code == 404


def test_create_mtf_strategy(client):
    r = client.post("/api/builder/strategies", json=MTF_CONFIG)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["schema_version"] == 2

    py_path = client.strategies_dir / "strategy_web_mtf_test.py"
    mod = _import_strategy(py_path)
    assert mod.SCHEMA_VERSION == 2
    assert mod.REQUIRED_TIMEFRAMES == ["H1", "H4"]
    assert len(mod.MTF_CONFIG["blocks"][0]["tiers"]) == 2
    # refs cualificadas con el primario (fix fase 0)
    assert mod.MTF_CONFIG["blocks"][0]["entry_condition"]["left"].startswith("H1.")


def test_create_mtf_rules_strategy(client):
    """Estrategia de reglas multi-timeframe: cualquier indicador por TF, vía API."""
    config = {
        "mode": "multi_timeframe",
        "display_name": "Web MTF Rules",
        "primary_timeframe": "H1",
        "indicators": [{"id": "RSI", "params": {"period": 14}, "timeframe": "H4"}],
        "buy_condition": {
            "type": "AND",
            "children": [
                {"type": "condition", "left": "H4.rsi_14", "op": "<", "right": 30},
                {"type": "condition", "left": "close", "op": ">", "right": 0},
            ],
        },
        "sell_condition": {"type": "condition", "left": "H4.rsi_14", "op": ">", "right": 70},
    }
    r = client.post("/api/builder/strategies", json=config)
    assert r.status_code == 201, r.text

    mod = _import_strategy(client.strategies_dir / "strategy_web_mtf_rules.py")
    assert mod.STRATEGY_TYPE == "rules"
    assert mod.REQUIRED_TIMEFRAMES == ["H1", "H4"]
    assert "rsi_14" not in str(mod.MTF_CONFIG.get("blocks"))  # sin bloques en modo reglas


def test_create_short_block_strategy(client):
    config = {
        "mode": "multi_timeframe",
        "display_name": "Web Short Block",
        "primary_timeframe": "M5",
        "indicators": [],
        "blocks": [
            {"id": "corto", "direction": "short", "trigger_timeframe": "M5", "risk_tiers": [0.01]}
        ],
    }
    r = client.post("/api/builder/strategies", json=config)
    assert r.status_code == 201, r.text
    mod = _import_strategy(client.strategies_dir / "strategy_web_short_block.py")
    block = mod.MTF_CONFIG["blocks"][0]
    assert block["direction"] == "short"
    assert "vortex_cross_down" in block["entry_condition"]["left"]


def test_validate_endpoint(client):
    ok = client.post("/api/builder/validate", json=V1_CONFIG).json()
    assert ok["valid"] is True and ok["errors"] == []

    bad = dict(V1_CONFIG)
    bad["buy_condition"] = {
        "type": "AND",
        "children": [{"type": "condition", "left": "rsi_14", "op": "<", "right": 30}],
    }
    res = client.post("/api/builder/validate", json=bad).json()
    assert res["valid"] is False
    assert "at least 2" in res["errors"][0]

    unknown = dict(V1_CONFIG)
    unknown["indicators"] = [{"id": "NOPE", "params": {}, "columns": [], "pre_computed": False}]
    res = client.post("/api/builder/validate", json=unknown).json()
    assert res["valid"] is False


def test_delete_strategy(client):
    client.post("/api/builder/strategies", json=V1_CONFIG)
    client.post("/api/strategies/strategy_web_rsi_test/enable")

    r = client.delete("/api/builder/strategies/strategy_web_rsi_test")
    assert r.status_code == 200
    assert not (client.strategies_dir / "strategy_web_rsi_test.py").exists()
    assert "strategy_web_rsi_test" not in core_config.ACTIVE_STRATEGIES

    assert client.delete("/api/builder/strategies/strategy_web_rsi_test").status_code == 404


def test_delete_handcrafted_refused(client):
    (client.strategies_dir / "strategy_manual.py").write_text(
        "def get_last_signal(df, verbose=False):\n    return 'none'\n", encoding="utf-8"
    )
    r = client.delete("/api/builder/strategies/strategy_manual")
    assert r.status_code == 400
    assert (client.strategies_dir / "strategy_manual.py").exists()
