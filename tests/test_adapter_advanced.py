"""
tests/test_adapter_advanced.py — La ruta v1/plan-executor ejecuta payloads avanzados.

LegacyStrategyAdapter debe traducir payloads con ATR/tramos de riesgo/piramidación
a acciones del plan (size_spec risk_pct, SL/TP en puntos desde el ATR, gating de
pirámide y límite de riesgo agregado), fiel a la ruta legacy directa y al backtest.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.runtime.adapter import LegacyStrategyAdapter
from backend.runtime.plan_interpreter import PlanInterpreter


def _context(owned_legs=None, ask=100.0, bid=99.9, equity=10_000.0):
    return {
        "symbol": {"name": "TEST"},
        "instance": {
            "id": "t::TEST",
            "strategy_key": "t",
            "runtime": {"legacy_execution_defaults": {"lot": 0.5, "sl_points": 300.0, "tp_points": 500.0}},
        },
        "instrument": {
            "symbol": "TEST", "point": 1.0, "tick_size": 1.0, "tick_value": 1.0,
            "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
        },
        "account": {"balance": equity, "equity": equity, "currency": "EUR"},
        "market": {
            "quote": {"ask": ask, "bid": bid, "mid": (ask + bid) / 2, "spread_points": 0.1},
            "frames": {"M1": {"bars": []}},
        },
        "execution": {"owned_legs": owned_legs or [], "owned_entry_groups": [], "broker_positions": []},
    }


class _AdvancedModule:
    """Estrategia fake que emite un payload avanzado fijo."""

    def __init__(self, signal, **overrides):
        self._payload = {
            "signal": signal,
            "reason": "tier hit",
            "pyramiding": True,
            "atr_value": 2.0,
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 3.0,
            "pyramid_atr_mult": 0.5,
            "risk_pct": 0.01,
            "entry_index": 0,
            "max_entries": 2,
            "block_id": "b", "tier_id": "t1",
        }
        self._payload.update(overrides)

    def get_last_signal_payload(self, df, verbose=False):
        return self._payload


def _leg(side="long", entry=100.0, sl=97.0, volume=0.5, group="g1", opened="2026-06-12T09:00:00Z"):
    return {"side": side, "status": "open", "avg_entry_price": entry, "stop_loss": sl,
            "remaining_volume": volume, "entry_group_id": group, "opened_at": opened}


def _decide(module, context):
    adapter = LegacyStrategyAdapter(module, "M1")
    return adapter.decide(context, {})["plan"]


def test_advanced_long_initial_entry():
    plan = _decide(_AdvancedModule("buy"), _context())
    assert plan["meta"]["compat_mode"] == "advanced_translation"
    assert len(plan["actions"]) == 1
    a = plan["actions"][0]
    assert a["type"] == "open_position" and a["side"] == "long"
    # SL/TP en puntos desde el ATR: 1.5*2.0/point(1.0) = 3.0 ; 3.0*2.0 = 6.0
    assert a["stop_spec"] == {"mode": "price_offset", "points": pytest.approx(3.0)}
    assert a["take_profit_spec"]["points"] == pytest.approx(6.0)
    # Tamaño por riesgo: 1% del equity
    assert a["size_spec"]["mode"] == "risk_pct"
    assert a["size_spec"]["value"] == pytest.approx(1.0)
    assert a["tags"]["entry_kind"] == "initial"

    # El interpreter lo resuelve a volumen y precios absolutos sin error
    norm = PlanInterpreter().validate_and_normalize(plan, _context())
    resolved = norm[0]["resolved"]
    # riesgo 100 EUR / (3 puntos * 1 EUR/punto/lote) = 33.33 lotes (clamp step 0.01)
    assert resolved["volume"] == pytest.approx(33.33, abs=0.01)
    assert resolved["sl_price"] == pytest.approx(99.95 - 3.0)  # mid - puntos
    assert resolved["tp_price"] == pytest.approx(99.95 + 6.0)


def test_advanced_short_initial_entry():
    plan = _decide(_AdvancedModule("sell"), _context())
    a = plan["actions"][0]
    assert a["side"] == "short" and a["type"] == "open_position"
    norm = PlanInterpreter().validate_and_normalize(plan, _context())
    resolved = norm[0]["resolved"]
    assert resolved["sl_price"] == pytest.approx(99.95 + 3.0)  # SL por encima en corto
    assert resolved["tp_price"] == pytest.approx(99.95 - 6.0)


def test_advanced_entry_index_gating():
    # entry_index=1 pero no hay legs abiertas → sin acciones
    plan = _decide(_AdvancedModule("buy", entry_index=1), _context())
    assert plan["actions"] == []


def test_advanced_max_entries_gating():
    legs = [_leg(), _leg(entry=101.5, group="g1", opened="2026-06-12T09:05:00Z")]
    plan = _decide(_AdvancedModule("buy", entry_index=None, max_entries=2), _context(owned_legs=legs))
    assert plan["actions"] == []


def test_advanced_pyramid_threshold_and_group():
    # Una leg larga a 100; umbral = 100 + 0.5*2 = 101
    legs = [_leg(entry=100.0)]
    # Precio por debajo del umbral → no piramida
    plan = _decide(_AdvancedModule("buy", entry_index=1), _context(owned_legs=legs, ask=100.5))
    assert plan["actions"] == []
    # Precio sobre el umbral → add_to_position al grupo existente
    plan = _decide(_AdvancedModule("buy", entry_index=1), _context(owned_legs=legs, ask=101.2))
    assert len(plan["actions"]) == 1
    a = plan["actions"][0]
    assert a["type"] == "add_to_position"
    assert a["tags"]["entry_kind"] == "pyramid"
    assert a["group_spec"] == {"mode": "existing_group", "target": {"mode": "by_id", "value": "g1"}}


def test_advanced_short_pyramid_threshold():
    legs = [_leg(side="short", entry=100.0, sl=103.0)]
    # Umbral corto = 100 - 1 = 99; bid por encima → no piramida
    plan = _decide(_AdvancedModule("sell", entry_index=1), _context(owned_legs=legs, bid=99.5))
    assert plan["actions"] == []
    # bid por debajo del umbral → piramida en corto
    plan = _decide(_AdvancedModule("sell", entry_index=1), _context(owned_legs=legs, bid=98.8))
    assert len(plan["actions"]) == 1
    assert plan["actions"][0]["side"] == "short"


def test_advanced_does_not_reverse_opposite_side():
    legs = [_leg(side="short", entry=100.0, sl=103.0)]
    plan = _decide(_AdvancedModule("buy"), _context(owned_legs=legs))
    assert plan["actions"] == []


def test_advanced_aggregate_risk_limit():
    # Legs existentes arriesgando ya ~2.5% (0.5 lotes * 5 puntos a 100 EUR... equity 100):
    # equity 1000, leg larga con riesgo 25 → 2.5%; nueva entrada 1% → 3.5% > 3% → bloqueada
    legs = [_leg(entry=100.0, sl=50.0, volume=0.5)]  # riesgo 25 EUR
    plan = _decide(_AdvancedModule("buy", entry_index=1), _context(owned_legs=legs, ask=102.0, equity=1000.0))
    assert plan["actions"] == []


def test_standard_signal_path_unchanged():
    class StdModule:
        @staticmethod
        def get_last_signal_payload(df, verbose=False):
            return {"signal": "buy", "reason": "std"}

    plan = _decide(StdModule(), _context())
    assert plan["meta"]["compat_mode"] == "signal_translation"
    assert len(plan["actions"]) == 1
    assert plan["actions"][0]["stop_spec"] == {"mode": "price_offset", "points": 300.0}


def test_paper_pyramid_directional():
    from backend.brokers.paper import PaperBrokerAdapter
    broker = PaperBrokerAdapter()
    broker.set_last_price("TEST", 100.0)

    res = broker.apply_pyramid_signal("TEST", 7, atr_value=2.0, lot=0.1,
                                      sl_atr_mult=1.5, tp_atr_mult=3.0, direction=-1)
    assert res and res["signal"] == "sell"
    pos = broker.get_open_positions("TEST", 7)[0]
    assert pos["direction"] == -1
    assert pos["sl"] == pytest.approx(103.0)  # SL por encima en corto
    assert pos["tp"] == pytest.approx(94.0)

    # Pirámide corta: precio debe BAJAR del umbral (100 - 0.5*2 = 99)
    broker.set_last_price("TEST", 99.5)
    assert broker.apply_pyramid_signal("TEST", 7, 2.0, 0.1, direction=-1) is None
    broker.set_last_price("TEST", 98.5)
    res2 = broker.apply_pyramid_signal("TEST", 7, 2.0, 0.1, direction=-1)
    assert res2 and len(broker.get_open_positions("TEST", 7)) == 2


if __name__ == "__main__":
    test_advanced_long_initial_entry()
    test_advanced_short_initial_entry()
    test_advanced_entry_index_gating()
    test_advanced_max_entries_gating()
    test_advanced_pyramid_threshold_and_group()
    test_advanced_short_pyramid_threshold()
    test_advanced_does_not_reverse_opposite_side()
    test_advanced_aggregate_risk_limit()
    test_standard_signal_path_unchanged()
    test_paper_pyramid_directional()
    print("All tests passed.")
