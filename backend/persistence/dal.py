# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Data Access Layer v1.

Expone:
- UnitOfWork: gestión de transacciones
- Repositorios por agregado
- Excepciones propias
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Excepciones propias
# ---------------------------------------------------------------------------

class PersistenceError(Exception):
    pass


class ConcurrencyConflictError(PersistenceError):
    pass


class SerializationError(PersistenceError):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return str(uuid.uuid4())


def _dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except Exception as exc:
        raise SerializationError(f"No se puede serializar a JSON: {exc}") from exc


def _loads(text: str | None) -> Any:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception as exc:
        raise SerializationError(f"No se puede deserializar JSON: {exc}") from exc


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Repositorios
# ---------------------------------------------------------------------------

class StrategyInstancesRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, instance_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM strategy_instances WHERE instance_id = ?", (instance_id,)
        ).fetchone()
        return _row_to_dict(row)

    def upsert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO strategy_instances
                (instance_id, strategy_key, symbol, status, book_revision,
                 created_at, updated_at, archived_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
                strategy_key  = excluded.strategy_key,
                symbol        = excluded.symbol,
                status        = excluded.status,
                updated_at    = excluded.updated_at,
                metadata_json = excluded.metadata_json
            """,
            (
                record["instance_id"],
                record["strategy_key"],
                record["symbol"],
                record.get("status", "active"),
                record.get("book_revision", 0),
                record.get("created_at", now),
                now,
                record.get("archived_at"),
                _dumps(record.get("metadata", {})),
            ),
        )

    def bump_revision(self, instance_id: str, expected_revision: int) -> int:
        result = self._conn.execute(
            """
            UPDATE strategy_instances
            SET book_revision = book_revision + 1, updated_at = ?
            WHERE instance_id = ? AND book_revision = ?
            """,
            (_now_utc(), instance_id, expected_revision),
        )
        if result.rowcount == 0:
            raise ConcurrencyConflictError(
                f"book_revision conflict para instancia {instance_id}: esperaba {expected_revision}"
            )
        return expected_revision + 1


class SymbolBooksRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, symbol: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM symbol_books WHERE symbol = ?", (symbol,)
        ).fetchone()
        return _row_to_dict(row)

    def upsert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO symbol_books
                (symbol, position_mode, ownership_mode, active_owner_instance_id,
                 book_revision, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                position_mode            = excluded.position_mode,
                ownership_mode           = excluded.ownership_mode,
                active_owner_instance_id = excluded.active_owner_instance_id,
                updated_at               = excluded.updated_at
            """,
            (
                record["symbol"],
                record.get("position_mode", "hedging"),
                record.get("ownership_mode", "shared"),
                record.get("active_owner_instance_id"),
                record.get("book_revision", 0),
                now,
            ),
        )

    def bump_revision(self, symbol: str, expected_revision: int) -> int:
        result = self._conn.execute(
            """
            UPDATE symbol_books
            SET book_revision = book_revision + 1, updated_at = ?
            WHERE symbol = ? AND book_revision = ?
            """,
            (_now_utc(), symbol, expected_revision),
        )
        if result.rowcount == 0:
            raise ConcurrencyConflictError(
                f"book_revision conflict para symbol {symbol}: esperaba {expected_revision}"
            )
        return expected_revision + 1


class StrategyStateRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, instance_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM strategy_state WHERE instance_id = ?", (instance_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["state"] = _loads(d.pop("state_json", "{}"))
        return d

    def upsert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO strategy_state
                (instance_id, strategy_key, symbol, schema_version, revision,
                 last_decision_id, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
                schema_version   = excluded.schema_version,
                revision         = excluded.revision,
                last_decision_id = excluded.last_decision_id,
                state_json       = excluded.state_json,
                updated_at       = excluded.updated_at
            """,
            (
                record["instance_id"],
                record["strategy_key"],
                record["symbol"],
                record.get("schema_version", 1),
                record.get("revision", 0),
                record.get("last_decision_id"),
                _dumps(record.get("state", {})),
                record.get("created_at", now),
                now,
            ),
        )

    def update_if_revision_matches(
        self, instance_id: str, expected_revision: int, new_record: dict
    ) -> None:
        now = _now_utc()
        result = self._conn.execute(
            """
            UPDATE strategy_state
            SET schema_version   = ?,
                revision         = ?,
                last_decision_id = ?,
                state_json       = ?,
                updated_at       = ?
            WHERE instance_id = ? AND revision = ?
            """,
            (
                new_record.get("schema_version", 1),
                new_record["revision"],
                new_record.get("last_decision_id"),
                _dumps(new_record.get("state", {})),
                now,
                instance_id,
                expected_revision,
            ),
        )
        if result.rowcount == 0:
            raise ConcurrencyConflictError(
                f"revision conflict para estado de instancia {instance_id}: esperaba {expected_revision}"
            )


class PlansRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO plans
                (plan_id, instance_id, strategy_key, symbol, iteration_id,
                 schema_version, status, action_count, state_revision_before,
                 symbol_book_revision_before, reason, plan_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["plan_id"],
                record["instance_id"],
                record["strategy_key"],
                record["symbol"],
                record.get("iteration_id", ""),
                record.get("schema_version", 1),
                record.get("status", "received"),
                record.get("action_count", 0),
                record.get("state_revision_before"),
                record.get("symbol_book_revision_before"),
                record.get("reason", ""),
                _dumps(record.get("plan", {})),
                record.get("created_at", now),
                now,
            ),
        )

    def get(self, plan_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["plan"] = _loads(d.pop("plan_json", "{}"))
        return d

    def exists(self, plan_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        return row is not None

    def update_status(self, plan_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE plans SET status = ?, updated_at = ? WHERE plan_id = ?",
            (status, _now_utc(), plan_id),
        )


class ExecutionReportsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO execution_reports
                (report_id, plan_id, instance_id, strategy_key, symbol, status,
                 summary, previous_state_revision, new_state_revision,
                 stats_json, report_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["report_id"],
                record["plan_id"],
                record["instance_id"],
                record["strategy_key"],
                record["symbol"],
                record.get("status", "executed"),
                record.get("summary", ""),
                record.get("previous_state_revision"),
                record.get("new_state_revision"),
                _dumps(record.get("stats", {})),
                _dumps(record.get("report", {})),
                record.get("created_at", now),
            ),
        )

    def get_by_plan(self, plan_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM execution_reports WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        return _row_to_dict(row)

    def list_latest_by_instance(self, instance_id: str, limit: int = 50) -> list:
        rows = self._conn.execute(
            """
            SELECT * FROM execution_reports
            WHERE instance_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (instance_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


class ActionReportsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO action_reports
                (action_report_id, report_id, plan_id, action_id, action_type,
                 symbol, status, message, requested_json, resolved_targets_json,
                 resolved_values_json, normalization_json, broker_result_json,
                 resource_effects_json, timing_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("action_report_id", _new_id()),
                record["report_id"],
                record["plan_id"],
                record["action_id"],
                record["action_type"],
                record["symbol"],
                record.get("status", "executed"),
                record.get("message", ""),
                _dumps(record.get("requested", {})),
                _dumps(record.get("resolved_targets", {})),
                _dumps(record.get("resolved_values", {})),
                _dumps(record.get("normalization", {})),
                _dumps(record.get("broker_result", {})),
                _dumps(record.get("resource_effects", {})),
                _dumps(record.get("timing", {})),
                record.get("created_at", now),
            ),
        )


class EntryGroupsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO entry_groups
                (entry_group_id, instance_id, strategy_key, symbol, side, status,
                 root_leg_id, created_by_plan_id, created_at, updated_at,
                 closed_at, tags_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["entry_group_id"],
                record["instance_id"],
                record["strategy_key"],
                record["symbol"],
                record["side"],
                record.get("status", "open"),
                record.get("root_leg_id"),
                record["created_by_plan_id"],
                record.get("created_at", now),
                now,
                record.get("closed_at"),
                _dumps(record.get("tags", {})),
            ),
        )

    def get(self, entry_group_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM entry_groups WHERE entry_group_id = ?", (entry_group_id,)
        ).fetchone()
        return _row_to_dict(row)

    def list_open_by_instance(self, instance_id: str) -> list:
        rows = self._conn.execute(
            """
            SELECT * FROM entry_groups
            WHERE instance_id = ? AND status IN ('open', 'partially_closed')
            ORDER BY created_at ASC
            """,
            (instance_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_group_state(self, entry_group_id: str, status: str, closed_at: str | None = None) -> None:
        self._conn.execute(
            "UPDATE entry_groups SET status = ?, updated_at = ?, closed_at = ? WHERE entry_group_id = ?",
            (status, _now_utc(), closed_at, entry_group_id),
        )

    def set_root_leg(self, entry_group_id: str, leg_id: str) -> None:
        self._conn.execute(
            "UPDATE entry_groups SET root_leg_id = ?, updated_at = ? WHERE entry_group_id = ?",
            (leg_id, _now_utc(), entry_group_id),
        )


class LegsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO legs
                (leg_id, instance_id, entry_group_id, strategy_key, symbol,
                 side, status, opened_by_plan_id, opened_by_action_id,
                 origin_order_id, requested_volume, opened_volume,
                 remaining_volume, avg_entry_price, stop_loss, take_profit,
                 opened_at, updated_at, closed_at, tags_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["leg_id"],
                record["instance_id"],
                record["entry_group_id"],
                record["strategy_key"],
                record["symbol"],
                record["side"],
                record.get("status", "open"),
                record["opened_by_plan_id"],
                record["opened_by_action_id"],
                record.get("origin_order_id"),
                record.get("requested_volume", 0.0),
                record.get("opened_volume", 0.0),
                record.get("remaining_volume", 0.0),
                record.get("avg_entry_price"),
                record.get("stop_loss"),
                record.get("take_profit"),
                record.get("opened_at", now),
                now,
                record.get("closed_at"),
                _dumps(record.get("tags", {})),
            ),
        )

    def get(self, leg_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM legs WHERE leg_id = ?", (leg_id,)
        ).fetchone()
        return _row_to_dict(row)

    def list_open_by_instance(self, instance_id: str) -> list:
        rows = self._conn.execute(
            """
            SELECT * FROM legs
            WHERE instance_id = ? AND status IN ('open', 'pending_open', 'reducing')
            ORDER BY opened_at ASC
            """,
            (instance_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_open_by_group(self, entry_group_id: str) -> list:
        rows = self._conn.execute(
            """
            SELECT * FROM legs
            WHERE entry_group_id = ? AND status IN ('open', 'pending_open', 'reducing')
            ORDER BY opened_at ASC
            """,
            (entry_group_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_leg_state(self, leg_id: str, updates: dict) -> None:
        allowed = {
            "status", "opened_volume", "remaining_volume", "avg_entry_price",
            "stop_loss", "take_profit", "opened_at", "closed_at", "origin_order_id",
        }
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return
        fields["updated_at"] = _now_utc()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [leg_id]
        self._conn.execute(
            f"UPDATE legs SET {set_clause} WHERE leg_id = ?", values
        )


class FillsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO fills
                (fill_id, instance_id, strategy_key, symbol, entry_group_id,
                 leg_id, order_id, side, fill_kind, volume, price,
                 commission, swap, broker_deal_id, broker_order_id,
                 broker_position_id, occurred_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("fill_id", _new_id()),
                record["instance_id"],
                record["strategy_key"],
                record["symbol"],
                record.get("entry_group_id"),
                record.get("leg_id"),
                record.get("order_id"),
                record["side"],
                record.get("fill_kind", "open"),
                record["volume"],
                record["price"],
                record.get("commission", 0.0),
                record.get("swap", 0.0),
                record.get("broker_deal_id"),
                record.get("broker_order_id"),
                record.get("broker_position_id"),
                record.get("occurred_at", now),
                _dumps(record.get("payload", {})),
            ),
        )

    def list_by_leg(self, leg_id: str) -> list:
        rows = self._conn.execute(
            "SELECT * FROM fills WHERE leg_id = ? ORDER BY occurred_at ASC",
            (leg_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_by_group(self, entry_group_id: str) -> list:
        rows = self._conn.execute(
            "SELECT * FROM fills WHERE entry_group_id = ? ORDER BY occurred_at ASC",
            (entry_group_id,),
        ).fetchall()
        return [dict(r) for r in rows]


class PendingOrdersRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO pending_orders
                (order_id, instance_id, entry_group_id, target_leg_id,
                 strategy_key, symbol, side, order_kind, status,
                 requested_volume, remaining_volume, limit_price, stop_price,
                 stop_loss, take_profit, broker_order_id,
                 opened_by_plan_id, opened_by_action_id,
                 created_at, updated_at, closed_at, spec_json, tags_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["order_id"],
                record["instance_id"],
                record.get("entry_group_id"),
                record.get("target_leg_id"),
                record["strategy_key"],
                record["symbol"],
                record["side"],
                record.get("order_kind", "limit"),
                record.get("status", "working"),
                record.get("requested_volume", 0.0),
                record.get("remaining_volume", 0.0),
                record.get("limit_price"),
                record.get("stop_price"),
                record.get("stop_loss"),
                record.get("take_profit"),
                record.get("broker_order_id"),
                record["opened_by_plan_id"],
                record["opened_by_action_id"],
                record.get("created_at", now),
                now,
                record.get("closed_at"),
                _dumps(record.get("spec", {})),
                _dumps(record.get("tags", {})),
            ),
        )

    def get(self, order_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM pending_orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        return _row_to_dict(row)

    def list_working_by_instance(self, instance_id: str) -> list:
        rows = self._conn.execute(
            """
            SELECT * FROM pending_orders
            WHERE instance_id = ? AND status IN ('working', 'partially_filled')
            ORDER BY created_at ASC
            """,
            (instance_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_status(self, order_id: str, status: str, closed_at: str | None = None) -> None:
        self._conn.execute(
            "UPDATE pending_orders SET status = ?, updated_at = ?, closed_at = ? WHERE order_id = ?",
            (status, _now_utc(), closed_at, order_id),
        )


class EventLogRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def append(self, record: dict) -> None:
        now = _now_utc()
        self._conn.execute(
            """
            INSERT INTO event_log
                (event_id, occurred_at, event_type, iteration_id, mode,
                 strategy_key, instance_id, symbol, plan_id, action_id,
                 report_id, entry_group_id, leg_id, order_id, fill_id,
                 broker_order_id, broker_position_id, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("event_id", _new_id()),
                record.get("occurred_at", now),
                record["event_type"],
                record.get("iteration_id"),
                record.get("mode", "live"),
                record.get("strategy_key"),
                record.get("instance_id"),
                record.get("symbol"),
                record.get("plan_id"),
                record.get("action_id"),
                record.get("report_id"),
                record.get("entry_group_id"),
                record.get("leg_id"),
                record.get("order_id"),
                record.get("fill_id"),
                record.get("broker_order_id"),
                record.get("broker_position_id"),
                _dumps(record.get("payload", {})),
            ),
        )

    def append_many(self, records: list) -> None:
        for record in records:
            self.append(record)

    def list_by_plan(self, plan_id: str) -> list:
        rows = self._conn.execute(
            "SELECT * FROM event_log WHERE plan_id = ? ORDER BY occurred_at ASC",
            (plan_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_by_instance(
        self, instance_id: str, from_ts: str | None = None, to_ts: str | None = None
    ) -> list:
        query = "SELECT * FROM event_log WHERE instance_id = ?"
        params: list = [instance_id]
        if from_ts:
            query += " AND occurred_at >= ?"
            params.append(from_ts)
        if to_ts:
            query += " AND occurred_at <= ?"
            params.append(to_ts)
        query += " ORDER BY occurred_at ASC"
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Unit of Work
# ---------------------------------------------------------------------------

class UnitOfWork:
    """
    Encapsula una transacción SQLite con acceso a todos los repositorios.

    Uso:
        uow = UnitOfWork(conn)
        with uow.immediate():
            uow.plans.insert(...)
            uow.event_log.append(...)
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.strategy_instances = StrategyInstancesRepository(conn)
        self.symbol_books = SymbolBooksRepository(conn)
        self.strategy_state = StrategyStateRepository(conn)
        self.plans = PlansRepository(conn)
        self.execution_reports = ExecutionReportsRepository(conn)
        self.action_reports = ActionReportsRepository(conn)
        self.entry_groups = EntryGroupsRepository(conn)
        self.legs = LegsRepository(conn)
        self.fills = FillsRepository(conn)
        self.pending_orders = PendingOrdersRepository(conn)
        self.event_log = EventLogRepository(conn)

    @contextmanager
    def immediate(self):
        """Transacción BEGIN IMMEDIATE — evita conflictos tardíos de escritura."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()
