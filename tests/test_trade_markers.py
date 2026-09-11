# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
tests/test_trade_markers.py — Tests de la capa pura de analítica de operaciones
(src/analytics/trade_history.py): emparejado round-trip, causa de cierre y puntos.

Run with: python tests/test_trade_markers.py
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.analytics.trade_history import (
    build_round_trips,
    points_from_price_delta,
    resolve_exit_cause,
)

# Valores oficiales de MT5 (coinciden con los defaults del módulo).
BUY, SELL = 0, 1
IN, OUT, INOUT = 0, 1, 2
R_CLIENT, R_EXPERT, R_SL, R_TP, R_SO = 0, 3, 4, 5, 6


def deal(**kw):
    base = {"type": BUY, "entry": IN, "position_id": 1, "time": 0,
            "price": 0.0, "volume": 1.0, "profit": 0.0, "reason": R_EXPERT}
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_resolve_exit_cause():
    assert resolve_exit_cause(deal(reason=R_SL)) == "SL"
    assert resolve_exit_cause(deal(reason=R_TP)) == "TP"
    assert resolve_exit_cause(deal(reason=R_SO)) == "Stop Out"
    assert resolve_exit_cause(deal(reason=R_EXPERT)) == "Reversión/Bot"
    assert resolve_exit_cause(deal(reason=R_CLIENT)) == "Manual"
    assert resolve_exit_cause(deal(reason=999)) == "Otro"
    assert resolve_exit_cause(deal(reason=None)) == ""
    print("PASS test_resolve_exit_cause")


def test_points_from_price_delta():
    assert points_from_price_delta(100.0, 102.0, "BUY", 0.01) == 200.0
    # Corto que baja de 100 a 98 => +200 puntos a favor.
    assert points_from_price_delta(100.0, 98.0, "SELL", 0.01) == 200.0
    # Corto que sube => puntos negativos.
    assert points_from_price_delta(100.0, 101.0, "SELL", 0.01) == -100.0
    assert points_from_price_delta(100.0, 102.0, "BUY", 0) == 0.0
    print("PASS test_points_from_price_delta")


def test_build_round_trips_basic():
    deals = [
        deal(type=BUY, entry=IN, position_id=7, time=100, price=100.0, volume=1.0),
        deal(type=SELL, entry=OUT, position_id=7, time=160, price=110.0, volume=1.0,
             profit=10.0, reason=R_TP),
    ]
    rts = build_round_trips(deals, 0.01)
    assert len(rts) == 1
    rt = rts[0]
    assert rt["direction"] == "BUY"
    assert rt["entry_price"] == 100.0 and rt["exit_price"] == 110.0
    assert rt["profit"] == 10.0
    assert rt["points"] == 1000.0  # (110-100)/0.01
    assert abs(rt["return_pct"] - 10.0) < 1e-9
    assert rt["duration_s"] == 60
    assert rt["exit_cause"] == "TP"
    print("PASS test_build_round_trips_basic")


def test_build_round_trips_skips_open():
    deals = [deal(type=BUY, entry=IN, position_id=9, time=10, price=100.0)]
    assert build_round_trips(deals, 0.01) == []
    print("PASS test_build_round_trips_skips_open")


def test_build_round_trips_partial_and_short():
    # Corto: IN vol 2 @100; dos OUT parciales @110 y @120 (precio medio 115).
    deals = [
        deal(type=SELL, entry=IN, position_id=3, time=10, price=100.0, volume=2.0),
        deal(type=BUY, entry=OUT, position_id=3, time=20, price=110.0, volume=1.0,
             profit=-10.0, reason=R_SL),
        deal(type=BUY, entry=OUT, position_id=3, time=30, price=120.0, volume=1.0,
             profit=-20.0, reason=R_SL),
    ]
    rts = build_round_trips(deals, 0.01)
    assert len(rts) == 1
    rt = rts[0]
    assert rt["direction"] == "SELL"
    assert rt["entry_price"] == 100.0
    assert rt["exit_price"] == 115.0  # ponderado por volumen
    assert rt["volume"] == 2.0
    assert rt["profit"] == -30.0
    # Corto que sube de 100 a 115 => puntos en contra (negativos).
    assert rt["points"] == -1500.0
    assert rt["exit_cause"] == "SL"  # del último OUT
    print("PASS test_build_round_trips_partial_and_short")


def test_build_round_trips_resolvers():
    deals = [
        deal(type=BUY, entry=IN, position_id=1, time=10, price=100.0),
        deal(type=SELL, entry=OUT, position_id=1, time=20, price=105.0, profit=5.0),
    ]
    rts = build_round_trips(
        deals, 0.01,
        strategy_resolver=lambda d: "MiEstrategia",
        reason_resolver=lambda d: "ema_cross_up",
    )
    assert rts[0]["strategy"] == "MiEstrategia"
    assert rts[0]["reason"] == "ema_cross_up"
    print("PASS test_build_round_trips_resolvers")


if __name__ == "__main__":
    test_resolve_exit_cause()
    test_points_from_price_delta()
    test_build_round_trips_basic()
    test_build_round_trips_skips_open()
    test_build_round_trips_partial_and_short()
    test_build_round_trips_resolvers()
    print("\nAll tests passed.")
