"""
Runner de migraciones para el schema SQLite v1.
"""

import sqlite3
from datetime import datetime, timezone

from .schema import MIGRATIONS


class MigrationError(Exception):
    pass


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_applied_versions(conn: sqlite3.Connection) -> set:
    try:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        return {row[0] for row in rows}
    except sqlite3.OperationalError:
        return set()


def apply_pending_migrations(conn: sqlite3.Connection) -> int:
    """
    Aplica las migraciones pendientes en orden.
    Devuelve el número de migraciones aplicadas.
    """
    applied = _get_applied_versions(conn)
    count = 0

    for version, name, sql in MIGRATIONS:
        if version in applied:
            continue
        try:
            # Ejecutar cada sentencia del bloque SQL separada por ;
            for statement in sql.split(";"):
                stmt = statement.strip()
                if stmt:
                    conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, _now_utc()),
            )
            conn.commit()
            count += 1
        except Exception as exc:
            conn.rollback()
            raise MigrationError(
                f"Error aplicando migración {version} ({name}): {exc}"
            ) from exc

    return count
