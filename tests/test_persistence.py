# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Tests para src/persistence/ — no requieren MT5 ni red.
"""

import sqlite3
import tempfile
import os
import pytest

from backend.persistence import bootstrap_persistence, UnitOfWork
from backend.persistence.migrations import apply_pending_migrations, MigrationError
from backend.persistence.dal import (
    StrategyInstancesRepository,
    PlansRepository,
    StrategyStateRepository,
    ExecutionReportsRepository,
    EventLogRepository,
    EntryGroupsRepository,
    LegsRepository,
    FillsRepository,
    ConcurrencyConflictError,
    SerializationError,
    _new_id,
    _now_utc,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def conn(db_path):
    c = bootstrap_persistence(db_path)
    yield c
    c.close()


@pytest.fixture
def uow(conn):
    return UnitOfWork(conn)


# ---------------------------------------------------------------------------
# Tests de migraciones
# ---------------------------------------------------------------------------

class TestMigrations:
    def test_bootstrap_creates_tables(self, conn):
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "schema_migrations", "strategy_instances", "symbol_books",
            "strategy_state", "plans", "execution_reports", "action_reports",
            "entry_groups", "legs", "pending_orders", "fills", "event_log",
        }
        assert expected.issubset(tables)

    def test_migrations_idempotent(self, db_path):
        c1 = bootstrap_persistence(db_path)
        c1.close()
        c2 = bootstrap_persistence(db_path)
        rows = c2.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        versions = [r[0] for r in rows]
        assert versions == sorted(set(versions))
        c2.close()

    def test_all_migrations_applied(self, conn):
        rows = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
        assert rows[0] >= 12  # Al menos las 12 migraciones definidas


# ---------------------------------------------------------------------------
# Tests de StrategyInstancesRepository
# ---------------------------------------------------------------------------

class TestStrategyInstancesRepository:
    def test_upsert_and_get(self, uow):
        instance_id = "strat_a::DE40"
        with uow.immediate():
            uow.strategy_instances.upsert({
                "instance_id": instance_id,
                "strategy_key": "strat_a",
                "symbol": "DE40",
                "status": "active",
            })
        record = uow.strategy_instances.get(instance_id)
        assert record is not None
        assert record["strategy_key"] == "strat_a"
        assert record["symbol"] == "DE40"

    def test_get_nonexistent_returns_none(self, uow):
        assert uow.strategy_instances.get("does_not_exist") is None

    def test_bump_revision(self, uow):
        instance_id = "strat_b::DE40"
        with uow.immediate():
            uow.strategy_instances.upsert({
                "instance_id": instance_id,
                "strategy_key": "strat_b",
                "symbol": "DE40",
                "status": "active",
            })
        with uow.immediate():
            new_rev = uow.strategy_instances.bump_revision(instance_id, 0)
        assert new_rev == 1

    def test_bump_revision_conflict(self, uow):
        instance_id = "strat_c::DE40"
        with uow.immediate():
            uow.strategy_instances.upsert({
                "instance_id": instance_id,
                "strategy_key": "strat_c",
                "symbol": "DE40",
                "status": "active",
            })
        with pytest.raises(ConcurrencyConflictError):
            with uow.immediate():
                uow.strategy_instances.bump_revision(instance_id, 99)


# ---------------------------------------------------------------------------
# Tests de StrategyStateRepository
# ---------------------------------------------------------------------------

class TestStrategyStateRepository:
    def _create_instance(self, uow, instance_id, strategy_key="strat_x", symbol="DE40"):
        with uow.immediate():
            uow.strategy_instances.upsert({
                "instance_id": instance_id,
                "strategy_key": strategy_key,
                "symbol": symbol,
                "status": "active",
            })

    def test_upsert_and_get(self, uow):
        instance_id = "strat_x::DE40"
        self._create_instance(uow, instance_id)
        with uow.immediate():
            uow.strategy_state.upsert({
                "instance_id": instance_id,
                "strategy_key": "strat_x",
                "symbol": "DE40",
                "schema_version": 1,
                "revision": 1,
                "state": {"strategy_state": {"count": 3}},
            })
        record = uow.strategy_state.get(instance_id)
        assert record is not None
        assert record["revision"] == 1
        assert record["state"]["strategy_state"]["count"] == 3

    def test_update_if_revision_matches(self, uow):
        instance_id = "strat_y::DE40"
        self._create_instance(uow, instance_id, "strat_y")
        with uow.immediate():
            uow.strategy_state.upsert({
                "instance_id": instance_id,
                "strategy_key": "strat_y",
                "symbol": "DE40",
                "schema_version": 1,
                "revision": 1,
                "state": {},
            })
        with uow.immediate():
            uow.strategy_state.update_if_revision_matches(
                instance_id, 1,
                {"schema_version": 1, "revision": 2, "state": {"strategy_state": {"x": 1}}}
            )
        record = uow.strategy_state.get(instance_id)
        assert record["revision"] == 2

    def test_update_conflict(self, uow):
        instance_id = "strat_z::DE40"
        self._create_instance(uow, instance_id, "strat_z")
        with uow.immediate():
            uow.strategy_state.upsert({
                "instance_id": instance_id,
                "strategy_key": "strat_z",
                "symbol": "DE40",
                "schema_version": 1,
                "revision": 5,
                "state": {},
            })
        with pytest.raises(ConcurrencyConflictError):
            with uow.immediate():
                uow.strategy_state.update_if_revision_matches(
                    instance_id, 3,
                    {"schema_version": 1, "revision": 4, "state": {}}
                )


# ---------------------------------------------------------------------------
# Tests de PlansRepository
# ---------------------------------------------------------------------------

class TestPlansRepository:
    def _setup_instance(self, uow, instance_id="inst::SYM", strategy_key="s", symbol="SYM"):
        with uow.immediate():
            uow.strategy_instances.upsert({
                "instance_id": instance_id,
                "strategy_key": strategy_key,
                "symbol": symbol,
                "status": "active",
            })

    def test_insert_and_get(self, uow):
        self._setup_instance(uow)
        plan_id = _new_id()
        with uow.immediate():
            uow.plans.insert({
                "plan_id": plan_id,
                "instance_id": "inst::SYM",
                "strategy_key": "s",
                "symbol": "SYM",
                "iteration_id": "iter_001",
                "schema_version": 1,
                "status": "received",
                "action_count": 1,
                "reason": "test",
                "plan": {"actions": []},
            })
        record = uow.plans.get(plan_id)
        assert record is not None
        assert record["plan_id"] == plan_id
        assert record["reason"] == "test"

    def test_exists(self, uow):
        self._setup_instance(uow)
        plan_id = _new_id()
        assert not uow.plans.exists(plan_id)
        with uow.immediate():
            uow.plans.insert({
                "plan_id": plan_id,
                "instance_id": "inst::SYM",
                "strategy_key": "s",
                "symbol": "SYM",
                "iteration_id": "",
                "schema_version": 1,
                "status": "received",
                "action_count": 0,
                "reason": "",
                "plan": {},
            })
        assert uow.plans.exists(plan_id)

    def test_update_status(self, uow):
        self._setup_instance(uow)
        plan_id = _new_id()
        with uow.immediate():
            uow.plans.insert({
                "plan_id": plan_id,
                "instance_id": "inst::SYM",
                "strategy_key": "s",
                "symbol": "SYM",
                "iteration_id": "",
                "schema_version": 1,
                "status": "received",
                "action_count": 0,
                "reason": "",
                "plan": {},
            })
        with uow.immediate():
            uow.plans.update_status(plan_id, "executed")
        record = uow.plans.get(plan_id)
        assert record["status"] == "executed"


# ---------------------------------------------------------------------------
# Tests de EventLogRepository
# ---------------------------------------------------------------------------

class TestEventLogRepository:
    def test_append_and_list_by_plan(self, uow):
        plan_id = _new_id()
        event_id = _new_id()
        with uow.immediate():
            uow.event_log.append({
                "event_id": event_id,
                "event_type": "plan_received",
                "mode": "live",
                "plan_id": plan_id,
                "payload": {"test": True},
            })
        events = uow.event_log.list_by_plan(plan_id)
        assert len(events) == 1
        assert events[0]["event_type"] == "plan_received"

    def test_append_many(self, uow):
        instance_id = "multi_inst::DE40"
        events = [
            {"event_type": f"event_{i}", "mode": "live", "instance_id": instance_id,
             "payload": {"i": i}}
            for i in range(5)
        ]
        with uow.immediate():
            uow.event_log.append_many(events)
        result = uow.event_log.list_by_instance(instance_id)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Tests de EntryGroups y Legs
# ---------------------------------------------------------------------------

class TestEntryGroupsAndLegs:
    def _setup(self, uow, instance_id="eng_inst::DE40", plan_id=None):
        plan_id = plan_id or _new_id()
        with uow.immediate():
            uow.strategy_instances.upsert({
                "instance_id": instance_id,
                "strategy_key": "eng_strat",
                "symbol": "DE40",
                "status": "active",
            })
            uow.plans.insert({
                "plan_id": plan_id,
                "instance_id": instance_id,
                "strategy_key": "eng_strat",
                "symbol": "DE40",
                "iteration_id": "",
                "schema_version": 1,
                "status": "executing",
                "action_count": 1,
                "reason": "test",
                "plan": {},
            })
        return plan_id

    def test_create_group_and_leg(self, uow):
        instance_id = "eng_inst::DE40"
        plan_id = self._setup(uow, instance_id)
        group_id = _new_id()
        leg_id = _new_id()
        now = _now_utc()

        with uow.immediate():
            uow.entry_groups.insert({
                "entry_group_id": group_id,
                "instance_id": instance_id,
                "strategy_key": "eng_strat",
                "symbol": "DE40",
                "side": "long",
                "status": "open",
                "created_by_plan_id": plan_id,
            })
            uow.legs.insert({
                "leg_id": leg_id,
                "instance_id": instance_id,
                "entry_group_id": group_id,
                "strategy_key": "eng_strat",
                "symbol": "DE40",
                "side": "long",
                "status": "open",
                "opened_by_plan_id": plan_id,
                "opened_by_action_id": _new_id(),
                "requested_volume": 0.1,
                "opened_volume": 0.1,
                "remaining_volume": 0.1,
                "avg_entry_price": 18400.0,
                "stop_loss": 18100.0,
                "take_profit": 18800.0,
            })

        group = uow.entry_groups.get(group_id)
        assert group is not None
        assert group["side"] == "long"

        legs = uow.legs.list_open_by_instance(instance_id)
        assert len(legs) == 1
        assert legs[0]["leg_id"] == leg_id

    def test_close_leg(self, uow):
        instance_id = "close_inst::DE40"
        plan_id = self._setup(uow, instance_id)
        group_id = _new_id()
        leg_id = _new_id()

        with uow.immediate():
            uow.entry_groups.insert({
                "entry_group_id": group_id,
                "instance_id": instance_id,
                "strategy_key": "eng_strat",
                "symbol": "DE40",
                "side": "long",
                "status": "open",
                "created_by_plan_id": plan_id,
            })
            uow.legs.insert({
                "leg_id": leg_id,
                "instance_id": instance_id,
                "entry_group_id": group_id,
                "strategy_key": "eng_strat",
                "symbol": "DE40",
                "side": "long",
                "status": "open",
                "opened_by_plan_id": plan_id,
                "opened_by_action_id": _new_id(),
                "requested_volume": 0.1,
                "opened_volume": 0.1,
                "remaining_volume": 0.1,
            })

        now = _now_utc()
        with uow.immediate():
            uow.legs.update_leg_state(leg_id, {
                "status": "closed",
                "remaining_volume": 0.0,
                "closed_at": now,
            })

        open_legs = uow.legs.list_open_by_instance(instance_id)
        assert len(open_legs) == 0
