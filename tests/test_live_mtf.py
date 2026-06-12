"""
tests/test_live_mtf.py — El análisis del loop en vivo soporta estrategias MTF.

Cubre el bug histórico: backend.main pasaba un único df del timeframe primario y
los módulos MTF nunca señalaban en vivo (condiciones de otros TF → None → False).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import main as live_main
from backend.strategy import runtime as strategy_runtime
from backend.strategy_builder.generator import build_strategy_module


def _base_df(n=180):
    idx = pd.date_range("2026-02-02 09:00", periods=n, freq="1min", tz="UTC")
    np.random.seed(11)
    close = pd.Series(100 + np.cumsum(np.random.randn(n) * 0.1 + 0.12))
    return pd.DataFrame({
        "time": idx,
        "open": close,
        "high": close + 0.4,
        "low": close - 0.4,
        "close": close,
        "tick_volume": np.ones(n) * 50,
    })


def _mtf_rules_module():
    config = {
        "mode": "multi_timeframe",
        "name": "live_mtf_rules",
        "display_name": "Live MTF Rules",
        "primary_timeframe": "M1",
        "magic_number": 24681,
        "indicators": [{"id": "EMA", "params": {"period": 5}, "timeframe": "M2"}],
        "buy_condition": {
            "type": "AND",
            "children": [
                {"type": "condition", "left": "close", "op": ">", "right": 0},
                {"type": "condition", "left": "M2.ema_5", "op": ">", "right": 0},
            ],
        },
        "sell_condition": {"type": "condition", "left": "close", "op": "<", "right": 0},
    }
    return build_strategy_module(config, module_name="live_mtf_rules_preview")


def _entry(module):
    return {
        "key": "live_mtf",
        "label": "live_mtf",
        "module": module,
        "timeframe_label": "M1",
        "required_timeframes": list(getattr(module, "REQUIRED_TIMEFRAMES", []) or ["M1"]),
        "params_values": {},
        "accepts_params": False,
        "magic_number": 24681,
    }


def test_analyze_strategy_mtf_produces_signal():
    module = _mtf_rules_module()
    market_cache = strategy_runtime.build_timeframe_frames(
        _base_df(), module.REQUIRED_TIMEFRAMES, base_timeframe="M1"
    )
    result = live_main._analyze_strategy(0, _entry(module), market_cache)
    assert not result["error"], result
    assert result["signal"] == "buy", result
    assert result["payload"]["reason"]


def test_analyze_strategy_mtf_missing_frame_reports_error():
    module = _mtf_rules_module()
    # Solo el frame M2: falta el primario M1 → error claro, no señal silenciosa.
    full = strategy_runtime.build_timeframe_frames(_base_df(), module.REQUIRED_TIMEFRAMES, base_timeframe="M1")
    result = live_main._analyze_strategy(0, _entry(module), {"M2": full["M2"]})
    assert result["error"] == "No hay suficientes velas"
    assert result["signal"] == "none"


def test_analyze_strategy_v1_still_works():
    from backend.strategy_builder.generator import build_strategy_module as build
    config = {
        "schema_version": 1,
        "name": "live_v1",
        "display_name": "Live V1",
        "description": "",
        "timeframe": "M1",
        "magic_number": 13579,
        "indicators": [{"id": "EMA", "params": {"period": 5}, "columns": ["ema_5"], "pre_computed": False}],
        "buy_condition": {
            "type": "AND",
            "children": [
                {"type": "condition", "left": "close", "op": ">", "right": 0},
                {"type": "condition", "left": "close", "op": ">", "right": "ema_5"},
            ],
        },
        "sell_condition": {
            "type": "AND",
            "children": [
                {"type": "condition", "left": "close", "op": "<", "right": 0},
                {"type": "condition", "left": "close", "op": "<", "right": "ema_5"},
            ],
        },
    }
    module = build(config, module_name="live_v1_preview")
    entry = _entry(module)
    entry["required_timeframes"] = ["M1"]
    result = live_main._analyze_strategy(0, entry, {"M1": _base_df()})
    assert not result["error"], result
    assert result["signal"] in ("buy", "sell", "none")


if __name__ == "__main__":
    test_analyze_strategy_mtf_produces_signal()
    test_analyze_strategy_mtf_missing_frame_reports_error()
    test_analyze_strategy_v1_still_works()
    print("All tests passed.")
