"""
Tests para src/runtime/ — no requieren MT5 ni red.
MT5 se mockea completamente.
"""

import types
import pytest
import pandas as pd

from src.runtime.adapter import LegacyStrategyAdapter, _extract_signal_payload, _get_owned_side
from src.runtime.plan_interpreter import PlanInterpreter, PlanValidationError
from src.runtime.state_store import StrategyStateStore
from src.persistence import bootstrap_persistence, UnitOfWork
from src.persistence.dal import _new_id


# ---------------------------------------------------------------------------
# Helpers de mock
# ---------------------------------------------------------------------------

def _make_legacy_module(signal: str = "buy", reason: str = "test reason"):
    m = types.ModuleType("mock_legacy")
    m.get_last_signal_payload = lambda df, verbose=False: {"signal": signal, "reason": reason}
    return m


def _make_v1_module(signal: str = "buy"):
    m = types.ModuleType("mock_v1")
    m.STRATEGY_API_VERSION = 1
    m.TIMEFRAME = "M15"

    def decide(context, state):
        side = "long" if signal == "buy" else "short" if signal == "sell" else None
        actions = []
        if side:
            actions.append({
                "action_id": _new_id(),
                "type": "open_position",
                "symbol": context.get("symbol", {}).get("name", "DE40"),
                "side": side,
                "size_spec": {"mode": "fixed_lots", "value": 0.1},
                "entry_spec": {"mode": "market"},
                "reason": "v1 test",
            })
        return {
            "plan": {
                "schema_version": 1,
                "plan_id": _new_id(),
                "instance_id": context.get("instance", {}).get("id", ""),
                "symbol": context.get("symbol", {}).get("name", "DE40"),
                "reason": f"v1 signal: {signal}",
                "actions": actions,
            },
            "next_state": {**state, "last_signal": signal},
        }

    m.decide = decide
    return m


def _make_context(
    symbol="DE40",
    instance_id="test_strat::DE40",
    strategy_key="test_strat",
    owned_side=None,
    equity=10000.0,
    bars=None,
    timeframe="M1",
):
    if bars is None:
        bars = [
            {
                "time": "2026-04-09T10:00:00Z",
                "open": 18400.0, "high": 18450.0, "low": 18380.0, "close": 18420.0,
                "tick_volume": 1200,
                "indicators": {"atr_14": 20.0, "adx_14": 30.0},
            },
            {
                "time": "2026-04-09T10:15:00Z",
                "open": 18420.0, "high": 18460.0, "low": 18410.0, "close": 18440.0,
                "tick_volume": 1100,
                "indicators": {"atr_14": 21.0, "adx_14": 32.0},
            },
        ]

    owned_legs = []
    if owned_side:
        owned_legs = [{
            "leg_id": _new_id(),
            "instance_id": instance_id,
            "side": owned_side,
            "status": "open",
            "remaining_volume": 0.1,
            "avg_entry_price": 18400.0,
        }]

    return {
        "run": {"mode": "live", "strategy_key": strategy_key, "symbol": symbol},
        "clock": {"now_utc": "2026-04-09T10:15:00Z"},
        "market": {
            "quote": {"bid": 18438.0, "ask": 18440.0, "mid": 18439.0, "spread_points": 2.0},
            "frames": {
                timeframe: {"bars": bars},
            },
        },
        "instrument": {
            "symbol": symbol,
            "digits": 1,
            "point": 0.1,
            "tick_size": 0.1,
            "tick_value": 1.0,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "stop_level_points": 0.0,
        },
        "account": {"balance": equity, "equity": equity, "margin_free": equity * 0.9},
        "portfolio": {"gross_exposure": 0.0, "open_risk_pct_equity": 0.0},
        "execution": {
            "broker_positions": [],
            "owned_legs": owned_legs,
            "owned_entry_groups": [],
        },
        "engine": {"max_actions_per_cycle": 20},
        "symbol": {"name": symbol},
        "instance": {
            "id": instance_id,
            "strategy_key": strategy_key,
            "runtime": {
                "legacy_execution_defaults": {"lot": 0.1, "sl_points": 300.0, "tp_points": 600.0}
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests de _extract_signal_payload
# ---------------------------------------------------------------------------

class TestExtractSignalPayload:
    def test_dict_with_signal_key(self):
        result = _extract_signal_payload({"signal": "buy", "reason": "EMA cross"})
        assert result["signal"] == "buy"
        assert result["reason"] == "EMA cross"

    def test_string_input(self):
        result = _extract_signal_payload("sell")
        assert result["signal"] == "sell"

    def test_invalid_signal_normalized_to_none(self):
        result = _extract_signal_payload("HOLD")
        assert result["signal"] == "none"

    def test_reason_truncated(self):
        long_reason = "x" * 200
        result = _extract_signal_payload({"signal": "buy", "reason": long_reason})
        assert len(result["reason"]) <= 160

    def test_tuple_input(self):
        result = _extract_signal_payload(("sell", "my reason"))
        assert result["signal"] == "sell"
        assert result["reason"] == "my reason"


# ---------------------------------------------------------------------------
# Tests de LegacyStrategyAdapter
# ---------------------------------------------------------------------------

class TestLegacyStrategyAdapter:
    def test_buy_signal_with_no_position(self):
        module = _make_legacy_module("buy", "EMA cross up")
        adapter = LegacyStrategyAdapter(module, "M1")
        context = _make_context(owned_side=None)
        result = adapter.decide(context, {})

        plan = result["plan"]
        assert plan["meta"]["origin"] == "legacy_adapter"
        assert plan["meta"]["legacy_signal"] == "buy"
        assert len(plan["actions"]) == 1
        assert plan["actions"][0]["type"] == "open_position"
        assert plan["actions"][0]["side"] == "long"

    def test_sell_signal_with_no_position(self):
        module = _make_legacy_module("sell")
        adapter = LegacyStrategyAdapter(module, "M1")
        context = _make_context(owned_side=None)
        result = adapter.decide(context, {})

        plan = result["plan"]
        assert plan["actions"][0]["side"] == "short"

    def test_buy_signal_already_long_is_noop(self):
        module = _make_legacy_module("buy")
        adapter = LegacyStrategyAdapter(module, "M1")
        context = _make_context(owned_side="long")
        result = adapter.decide(context, {})

        plan = result["plan"]
        assert len(plan["actions"]) == 0

    def test_buy_signal_with_short_position_close_and_open(self):
        module = _make_legacy_module("buy")
        adapter = LegacyStrategyAdapter(module, "M1")
        context = _make_context(owned_side="short")
        result = adapter.decide(context, {})

        plan = result["plan"]
        assert len(plan["actions"]) == 2
        assert plan["actions"][0]["type"] == "close_position"
        assert plan["actions"][1]["type"] == "open_position"
        assert plan["actions"][1]["side"] == "long"

    def test_none_signal_produces_empty_actions(self):
        module = _make_legacy_module("none")
        adapter = LegacyStrategyAdapter(module, "M1")
        context = _make_context()
        result = adapter.decide(context, {})
        assert result["plan"]["actions"] == []

    def test_next_state_preserves_existing(self):
        module = _make_legacy_module("buy")
        adapter = LegacyStrategyAdapter(module, "M1")
        context = _make_context()
        state = {"custom_key": 42}
        result = adapter.decide(context, state)
        assert result["next_state"]["custom_key"] == 42
        assert result["next_state"]["last_signal"] == "buy"

    def test_module_exception_produces_empty_plan(self):
        module = types.ModuleType("bad_module")
        def bad_signal(df):
            raise RuntimeError("strategy crash")
        module.get_last_signal = bad_signal
        adapter = LegacyStrategyAdapter(module, "M1")
        context = _make_context()
        result = adapter.decide(context, {})
        assert result["plan"]["actions"] == []
        assert "error" in result["plan"]["meta"]


# ---------------------------------------------------------------------------
# Tests de PlanInterpreter
# ---------------------------------------------------------------------------

class TestPlanInterpreter:
    def test_validate_empty_actions(self):
        interpreter = PlanInterpreter()
        plan = {
            "schema_version": 1,
            "plan_id": _new_id(),
            "instance_id": "inst::DE40",
            "symbol": "DE40",
            "reason": "test",
            "actions": [],
        }
        result = interpreter.validate_and_normalize(plan, _make_context())
        assert result == []

    def test_validate_open_position_fixed_lots(self):
        interpreter = PlanInterpreter()
        context = _make_context()
        plan = {
            "schema_version": 1,
            "plan_id": _new_id(),
            "instance_id": "inst::DE40",
            "symbol": "DE40",
            "reason": "ADX cross",
            "actions": [
                {
                    "action_id": "act_001",
                    "type": "open_position",
                    "symbol": "DE40",
                    "side": "long",
                    "size_spec": {"mode": "fixed_lots", "value": 0.1},
                    "entry_spec": {"mode": "market"},
                    "stop_spec": {"mode": "price_offset", "points": 300.0},
                    "take_profit_spec": {"mode": "rr_multiple", "multiple": 2.0},
                    "reason": "entrada",
                }
            ],
        }
        normalized = interpreter.validate_and_normalize(plan, context)
        assert len(normalized) == 1
        assert normalized[0]["type"] == "open_position"
        assert normalized[0]["resolved"]["volume"] == pytest.approx(0.1)
        assert normalized[0]["resolved"]["sl_price"] is not None
        assert normalized[0]["resolved"]["tp_price"] is not None

    def test_validate_open_position_risk_pct(self):
        interpreter = PlanInterpreter()
        context = _make_context(equity=10000.0)
        plan = {
            "schema_version": 1,
            "plan_id": _new_id(),
            "instance_id": "inst::DE40",
            "symbol": "DE40",
            "reason": "test",
            "actions": [
                {
                    "action_id": "act_002",
                    "type": "open_position",
                    "symbol": "DE40",
                    "side": "long",
                    "size_spec": {
                        "mode": "risk_pct_of_equity",
                        "value": 1.0,
                        "stop_points": 300.0,
                    },
                    "entry_spec": {"mode": "market"},
                    "reason": "riesgo",
                }
            ],
        }
        normalized = interpreter.validate_and_normalize(plan, context)
        assert normalized[0]["resolved"]["volume"] > 0

    def test_invalid_schema_version_raises(self):
        interpreter = PlanInterpreter()
        plan = {"schema_version": 99, "actions": []}
        with pytest.raises(PlanValidationError):
            interpreter.validate_and_normalize(plan, _make_context())

    def test_unsupported_action_type_raises(self):
        interpreter = PlanInterpreter()
        plan = {
            "schema_version": 1,
            "symbol": "DE40",
            "actions": [{"action_id": "x", "type": "do_magic", "symbol": "DE40", "reason": ""}],
        }
        with pytest.raises(PlanValidationError):
            interpreter.validate_and_normalize(plan, _make_context())

    def test_close_position_normalized(self):
        interpreter = PlanInterpreter()
        context = _make_context(owned_side="long")
        plan = {
            "schema_version": 1,
            "symbol": "DE40",
            "actions": [
                {
                    "action_id": "act_close",
                    "type": "close_position",
                    "symbol": "DE40",
                    "target": {"resource_type": "owned_side", "mode": "by_side", "value": "long"},
                    "reason": "cierre",
                }
            ],
        }
        normalized = interpreter.validate_and_normalize(plan, context)
        assert len(normalized) == 1
        assert normalized[0]["type"] == "close_position"

    def test_atr_multiple_stop(self):
        interpreter = PlanInterpreter()
        context = _make_context()
        plan = {
            "schema_version": 1,
            "symbol": "DE40",
            "actions": [
                {
                    "action_id": "act_atr",
                    "type": "open_position",
                    "symbol": "DE40",
                    "side": "long",
                    "size_spec": {"mode": "fixed_lots", "value": 0.05},
                    "entry_spec": {"mode": "market"},
                    "stop_spec": {"mode": "atr_multiple", "atr_period": 14, "multiple": 1.5},
                    "take_profit_spec": {"mode": "rr_multiple", "multiple": 2.0},
                    "reason": "atr stop test",
                }
            ],
        }
        normalized = interpreter.validate_and_normalize(plan, context)
        sl = normalized[0]["resolved"]["sl_price"]
        # ATR=21 en el último bar, múltiplo 1.5, punto 0.1 → offset = 21*1.5 = 31.5 puntos
        assert sl is not None
        assert sl < 18440.0  # SL debe estar por debajo del precio para long


# ---------------------------------------------------------------------------
# Tests de StrategyStateStore
# ---------------------------------------------------------------------------

class TestStrategyStateStore:
    @pytest.fixture
    def db_uow(self, tmp_path):
        db_path = str(tmp_path / "state_test.db")
        conn = bootstrap_persistence(db_path)
        uow = UnitOfWork(conn)
        yield uow
        conn.close()

    def _create_instance(self, uow, instance_id, strategy_key="s", symbol="DE40"):
        with uow.immediate():
            uow.strategy_instances.upsert({
                "instance_id": instance_id,
                "strategy_key": strategy_key,
                "symbol": symbol,
                "status": "active",
            })

    def test_load_empty_returns_defaults(self, db_uow):
        store = StrategyStateStore(db_uow)
        state, revision = store.load("nonexistent::DE40")
        assert state == {}
        assert revision == 0

    def test_save_and_load(self, db_uow):
        instance_id = "save_test::DE40"
        self._create_instance(db_uow, instance_id)
        store = StrategyStateStore(db_uow)
        new_rev = store.save(
            instance_id=instance_id,
            strategy_key="s",
            symbol="DE40",
            strategy_state={"count": 5, "last_side": "long"},
        )
        assert new_rev == 1

        state, rev = store.load(instance_id)
        assert rev == 1
        assert state["count"] == 5
        assert state["last_side"] == "long"

    def test_save_increments_revision(self, db_uow):
        instance_id = "rev_test::DE40"
        self._create_instance(db_uow, instance_id)
        store = StrategyStateStore(db_uow)
        r1 = store.save(instance_id, "s", "DE40", {"x": 1})
        r2 = store.save(instance_id, "s", "DE40", {"x": 2})
        r3 = store.save(instance_id, "s", "DE40", {"x": 3})
        assert r1 == 1
        assert r2 == 2
        assert r3 == 3

    def test_get_or_initialize_calls_initial_state(self, db_uow):
        instance_id = "init_test::DE40"
        self._create_instance(db_uow, instance_id)

        module = types.ModuleType("init_module")
        module.initial_state = lambda ctx: {"initialized": True, "count": 0}

        store = StrategyStateStore(db_uow)
        context = _make_context()
        state, rev = store.get_or_initialize(instance_id, "s", "DE40", module, context)
        assert state["initialized"] is True
        assert rev == 0

    def test_get_or_initialize_existing_state_not_reinit(self, db_uow):
        instance_id = "noinit_test::DE40"
        self._create_instance(db_uow, instance_id)
        store = StrategyStateStore(db_uow)
        store.save(instance_id, "s", "DE40", {"custom": 99})

        module = types.ModuleType("init_module2")
        module.initial_state = lambda ctx: {"initialized": True}

        context = _make_context()
        state, rev = store.get_or_initialize(instance_id, "s", "DE40", module, context)
        assert state.get("custom") == 99
        assert rev == 1


# ---------------------------------------------------------------------------
# Tests de integración v1 module
# ---------------------------------------------------------------------------

class TestV1ModuleDecide:
    def test_buy_signal_produces_open_position(self):
        module = _make_v1_module("buy")
        context = _make_context()
        result = module.decide(context, {})

        plan = result["plan"]
        assert plan["schema_version"] == 1
        assert len(plan["actions"]) == 1
        assert plan["actions"][0]["type"] == "open_position"
        assert plan["actions"][0]["side"] == "long"

    def test_none_signal_produces_empty_actions(self):
        module = _make_v1_module("none")
        context = _make_context()
        result = module.decide(context, {})
        assert result["plan"]["actions"] == []

    def test_next_state_updated(self):
        module = _make_v1_module("sell")
        context = _make_context()
        result = module.decide(context, {"existing": True})
        assert result["next_state"]["last_signal"] == "sell"
        assert result["next_state"]["existing"] is True
