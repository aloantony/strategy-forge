"""
Módulo de persistencia v1.
Expone bootstrap_persistence() como punto de entrada único.
"""

import sqlite3

from .migrations import apply_pending_migrations
from .dal import UnitOfWork
from .schema import PRAGMAS


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS.strip().split(";"):
        stmt = pragma.strip()
        if stmt:
            conn.execute(stmt)


def open_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    _configure_connection(conn)
    return conn


def bootstrap_persistence(db_path: str) -> sqlite3.Connection:
    """
    Abre la conexión SQLite, aplica PRAGMAs y ejecuta migraciones pendientes.
    Devuelve la conexión lista para usar.
    """
    conn = open_connection(db_path)
    apply_pending_migrations(conn)
    return conn


__all__ = ["bootstrap_persistence", "open_connection", "UnitOfWork"]
