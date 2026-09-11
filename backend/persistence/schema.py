# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
DDL completo del schema SQLite v1.
Todas las sentencias CREATE TABLE y CREATE INDEX según doc 13.
"""

PRAGMAS = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
"""

PRAGMAS_RELAXED = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
"""

# Lista de migraciones en orden. Cada entrada: (version, name, sql)
MIGRATIONS = [
    (
        1,
        "create_schema_migrations",
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version      INTEGER PRIMARY KEY,
            name         TEXT NOT NULL UNIQUE,
            applied_at   TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        "create_strategy_instances",
        """
        CREATE TABLE IF NOT EXISTS strategy_instances (
            instance_id         TEXT PRIMARY KEY,
            strategy_key        TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            status              TEXT NOT NULL
                                CHECK (status IN ('active', 'archived')),
            book_revision       INTEGER NOT NULL DEFAULT 0
                                CHECK (book_revision >= 0),
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            archived_at         TEXT,
            metadata_json       TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_strategy_instances_key_symbol
            ON strategy_instances(strategy_key, symbol);
        CREATE INDEX IF NOT EXISTS idx_strategy_instances_status
            ON strategy_instances(status);
        """,
    ),
    (
        3,
        "create_symbol_books",
        """
        CREATE TABLE IF NOT EXISTS symbol_books (
            symbol                   TEXT PRIMARY KEY,
            position_mode            TEXT NOT NULL
                                     CHECK (position_mode IN ('hedging', 'netting')),
            ownership_mode           TEXT NOT NULL
                                     CHECK (ownership_mode IN ('shared', 'single_owner_per_symbol')),
            active_owner_instance_id TEXT,
            book_revision            INTEGER NOT NULL DEFAULT 0
                                     CHECK (book_revision >= 0),
            updated_at               TEXT NOT NULL,
            FOREIGN KEY (active_owner_instance_id)
                REFERENCES strategy_instances(instance_id)
        );
        """,
    ),
    (
        4,
        "create_strategy_state",
        """
        CREATE TABLE IF NOT EXISTS strategy_state (
            instance_id           TEXT PRIMARY KEY,
            strategy_key          TEXT NOT NULL,
            symbol                TEXT NOT NULL,
            schema_version        INTEGER NOT NULL,
            revision              INTEGER NOT NULL
                                  CHECK (revision >= 0),
            last_decision_id      TEXT,
            state_json            TEXT NOT NULL,
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL,
            FOREIGN KEY (instance_id)
                REFERENCES strategy_instances(instance_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_strategy_state_revision
            ON strategy_state(revision);
        """,
    ),
    (
        5,
        "create_plans",
        """
        CREATE TABLE IF NOT EXISTS plans (
            plan_id                     TEXT PRIMARY KEY,
            instance_id                 TEXT NOT NULL,
            strategy_key                TEXT NOT NULL,
            symbol                      TEXT NOT NULL,
            iteration_id                TEXT NOT NULL,
            schema_version              INTEGER NOT NULL,
            status                      TEXT NOT NULL
                                        CHECK (status IN (
                                            'received',
                                            'validated',
                                            'executing',
                                            'executed',
                                            'partially_executed',
                                            'rejected_structural',
                                            'rejected_technical',
                                            'rejected_broker',
                                            'duplicate_skipped',
                                            'error'
                                        )),
            action_count                INTEGER NOT NULL
                                        CHECK (action_count >= 0),
            state_revision_before       INTEGER,
            symbol_book_revision_before INTEGER,
            reason                      TEXT NOT NULL,
            plan_json                   TEXT NOT NULL,
            created_at                  TEXT NOT NULL,
            updated_at                  TEXT NOT NULL,
            FOREIGN KEY (instance_id)
                REFERENCES strategy_instances(instance_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_plans_instance_created
            ON plans(instance_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_plans_iteration
            ON plans(iteration_id);
        CREATE INDEX IF NOT EXISTS idx_plans_status
            ON plans(status);
        """,
    ),
    (
        6,
        "create_execution_reports",
        """
        CREATE TABLE IF NOT EXISTS execution_reports (
            report_id                TEXT PRIMARY KEY,
            plan_id                  TEXT NOT NULL UNIQUE,
            instance_id              TEXT NOT NULL,
            strategy_key             TEXT NOT NULL,
            symbol                   TEXT NOT NULL,
            status                   TEXT NOT NULL
                                     CHECK (status IN (
                                         'accepted',
                                         'executed',
                                         'partially_executed',
                                         'rejected_structural',
                                         'rejected_technical',
                                         'rejected_broker',
                                         'duplicate_skipped',
                                         'error'
                                     )),
            summary                  TEXT NOT NULL,
            previous_state_revision  INTEGER,
            new_state_revision       INTEGER,
            stats_json               TEXT NOT NULL,
            report_json              TEXT NOT NULL,
            created_at               TEXT NOT NULL,
            FOREIGN KEY (plan_id)
                REFERENCES plans(plan_id)
                ON DELETE CASCADE,
            FOREIGN KEY (instance_id)
                REFERENCES strategy_instances(instance_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_execution_reports_instance_created
            ON execution_reports(instance_id, created_at);
        """,
    ),
    (
        7,
        "create_action_reports",
        """
        CREATE TABLE IF NOT EXISTS action_reports (
            action_report_id      TEXT PRIMARY KEY,
            report_id             TEXT NOT NULL,
            plan_id               TEXT NOT NULL,
            action_id             TEXT NOT NULL,
            action_type           TEXT NOT NULL,
            symbol                TEXT NOT NULL,
            status                TEXT NOT NULL
                                  CHECK (status IN (
                                      'validated',
                                      'executed',
                                      'partially_executed',
                                      'rejected_technical',
                                      'rejected_broker',
                                      'skipped_duplicate',
                                      'not_supported',
                                      'error'
                                  )),
            message               TEXT NOT NULL,
            requested_json        TEXT NOT NULL,
            resolved_targets_json TEXT NOT NULL,
            resolved_values_json  TEXT NOT NULL,
            normalization_json    TEXT NOT NULL,
            broker_result_json    TEXT NOT NULL,
            resource_effects_json TEXT NOT NULL,
            timing_json           TEXT NOT NULL,
            created_at            TEXT NOT NULL,
            FOREIGN KEY (report_id)
                REFERENCES execution_reports(report_id)
                ON DELETE CASCADE,
            FOREIGN KEY (plan_id)
                REFERENCES plans(plan_id)
                ON DELETE CASCADE,
            UNIQUE (plan_id, action_id)
        );
        CREATE INDEX IF NOT EXISTS idx_action_reports_status
            ON action_reports(status);
        CREATE INDEX IF NOT EXISTS idx_action_reports_plan
            ON action_reports(plan_id);
        """,
    ),
    (
        8,
        "create_entry_groups",
        """
        CREATE TABLE IF NOT EXISTS entry_groups (
            entry_group_id       TEXT PRIMARY KEY,
            instance_id          TEXT NOT NULL,
            strategy_key         TEXT NOT NULL,
            symbol               TEXT NOT NULL,
            side                 TEXT NOT NULL
                                 CHECK (side IN ('long', 'short')),
            status               TEXT NOT NULL
                                 CHECK (status IN ('open', 'partially_closed', 'closed', 'cancelled')),
            root_leg_id          TEXT,
            created_by_plan_id   TEXT NOT NULL,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            closed_at            TEXT,
            tags_json            TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (instance_id)
                REFERENCES strategy_instances(instance_id)
                ON DELETE CASCADE,
            FOREIGN KEY (created_by_plan_id)
                REFERENCES plans(plan_id)
        );
        CREATE INDEX IF NOT EXISTS idx_entry_groups_instance_status
            ON entry_groups(instance_id, status);
        CREATE INDEX IF NOT EXISTS idx_entry_groups_symbol_status
            ON entry_groups(symbol, status);
        """,
    ),
    (
        9,
        "create_legs",
        """
        CREATE TABLE IF NOT EXISTS legs (
            leg_id                  TEXT PRIMARY KEY,
            instance_id             TEXT NOT NULL,
            entry_group_id          TEXT NOT NULL,
            strategy_key            TEXT NOT NULL,
            symbol                  TEXT NOT NULL,
            side                    TEXT NOT NULL
                                    CHECK (side IN ('long', 'short')),
            status                  TEXT NOT NULL
                                    CHECK (status IN ('pending_open', 'open', 'reducing', 'closed', 'cancelled')),
            opened_by_plan_id       TEXT NOT NULL,
            opened_by_action_id     TEXT NOT NULL,
            origin_order_id         TEXT,
            requested_volume        REAL NOT NULL
                                    CHECK (requested_volume >= 0),
            opened_volume           REAL NOT NULL
                                    CHECK (opened_volume >= 0),
            remaining_volume        REAL NOT NULL
                                    CHECK (remaining_volume >= 0),
            avg_entry_price         REAL,
            stop_loss               REAL,
            take_profit             REAL,
            opened_at               TEXT,
            updated_at              TEXT NOT NULL,
            closed_at               TEXT,
            tags_json               TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (instance_id)
                REFERENCES strategy_instances(instance_id)
                ON DELETE CASCADE,
            FOREIGN KEY (entry_group_id)
                REFERENCES entry_groups(entry_group_id)
                ON DELETE CASCADE,
            FOREIGN KEY (opened_by_plan_id)
                REFERENCES plans(plan_id),
            CHECK (remaining_volume <= opened_volume)
        );
        CREATE INDEX IF NOT EXISTS idx_legs_instance_status
            ON legs(instance_id, status);
        CREATE INDEX IF NOT EXISTS idx_legs_group
            ON legs(entry_group_id);
        CREATE INDEX IF NOT EXISTS idx_legs_symbol_status
            ON legs(symbol, status);
        """,
    ),
    (
        10,
        "create_pending_orders",
        """
        CREATE TABLE IF NOT EXISTS pending_orders (
            order_id               TEXT PRIMARY KEY,
            instance_id            TEXT NOT NULL,
            entry_group_id         TEXT,
            target_leg_id          TEXT,
            strategy_key           TEXT NOT NULL,
            symbol                 TEXT NOT NULL,
            side                   TEXT NOT NULL
                                   CHECK (side IN ('long', 'short')),
            order_kind             TEXT NOT NULL
                                   CHECK (order_kind IN ('limit', 'stop')),
            status                 TEXT NOT NULL
                                   CHECK (status IN ('working', 'partially_filled', 'filled', 'cancelled', 'rejected', 'expired')),
            requested_volume       REAL NOT NULL
                                   CHECK (requested_volume >= 0),
            remaining_volume       REAL NOT NULL
                                   CHECK (remaining_volume >= 0),
            limit_price            REAL,
            stop_price             REAL,
            stop_loss              REAL,
            take_profit            REAL,
            broker_order_id        TEXT,
            opened_by_plan_id      TEXT NOT NULL,
            opened_by_action_id    TEXT NOT NULL,
            created_at             TEXT NOT NULL,
            updated_at             TEXT NOT NULL,
            closed_at              TEXT,
            spec_json              TEXT NOT NULL,
            tags_json              TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (instance_id)
                REFERENCES strategy_instances(instance_id)
                ON DELETE CASCADE,
            FOREIGN KEY (entry_group_id)
                REFERENCES entry_groups(entry_group_id),
            FOREIGN KEY (target_leg_id)
                REFERENCES legs(leg_id),
            FOREIGN KEY (opened_by_plan_id)
                REFERENCES plans(plan_id),
            CHECK (remaining_volume <= requested_volume)
        );
        CREATE INDEX IF NOT EXISTS idx_pending_orders_instance_status
            ON pending_orders(instance_id, status);
        CREATE INDEX IF NOT EXISTS idx_pending_orders_broker_order_id
            ON pending_orders(broker_order_id);
        """,
    ),
    (
        11,
        "create_fills",
        """
        CREATE TABLE IF NOT EXISTS fills (
            fill_id               TEXT PRIMARY KEY,
            instance_id           TEXT NOT NULL,
            strategy_key          TEXT NOT NULL,
            symbol                TEXT NOT NULL,
            entry_group_id        TEXT,
            leg_id                TEXT,
            order_id              TEXT,
            side                  TEXT NOT NULL
                                  CHECK (side IN ('long', 'short')),
            fill_kind             TEXT NOT NULL
                                  CHECK (fill_kind IN ('open', 'reduce', 'close')),
            volume                REAL NOT NULL
                                  CHECK (volume > 0),
            price                 REAL NOT NULL
                                  CHECK (price > 0),
            commission            REAL NOT NULL DEFAULT 0,
            swap                  REAL NOT NULL DEFAULT 0,
            broker_deal_id        TEXT,
            broker_order_id       TEXT,
            broker_position_id    TEXT,
            occurred_at           TEXT NOT NULL,
            payload_json          TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (instance_id)
                REFERENCES strategy_instances(instance_id)
                ON DELETE CASCADE,
            FOREIGN KEY (entry_group_id)
                REFERENCES entry_groups(entry_group_id),
            FOREIGN KEY (leg_id)
                REFERENCES legs(leg_id),
            FOREIGN KEY (order_id)
                REFERENCES pending_orders(order_id)
        );
        CREATE INDEX IF NOT EXISTS idx_fills_leg
            ON fills(leg_id);
        CREATE INDEX IF NOT EXISTS idx_fills_group
            ON fills(entry_group_id);
        CREATE INDEX IF NOT EXISTS idx_fills_broker_deal_id
            ON fills(broker_deal_id);
        CREATE INDEX IF NOT EXISTS idx_fills_occurred_at
            ON fills(occurred_at);
        """,
    ),
    (
        12,
        "create_event_log",
        # Sin FKs duras para robustez append-only (doc 13)
        """
        CREATE TABLE IF NOT EXISTS event_log (
            event_id              TEXT PRIMARY KEY,
            occurred_at           TEXT NOT NULL,
            event_type            TEXT NOT NULL,
            iteration_id          TEXT,
            mode                  TEXT NOT NULL,
            strategy_key          TEXT,
            instance_id           TEXT,
            symbol                TEXT,
            plan_id               TEXT,
            action_id             TEXT,
            report_id             TEXT,
            entry_group_id        TEXT,
            leg_id                TEXT,
            order_id              TEXT,
            fill_id               TEXT,
            broker_order_id       TEXT,
            broker_position_id    TEXT,
            payload_json          TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_event_log_occurred_at
            ON event_log(occurred_at);
        CREATE INDEX IF NOT EXISTS idx_event_log_plan
            ON event_log(plan_id);
        CREATE INDEX IF NOT EXISTS idx_event_log_action
            ON event_log(action_id);
        CREATE INDEX IF NOT EXISTS idx_event_log_instance_time
            ON event_log(instance_id, occurred_at);
        CREATE INDEX IF NOT EXISTS idx_event_log_leg
            ON event_log(leg_id);
        """,
    ),
]
