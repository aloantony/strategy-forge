"""Analítica de operaciones: emparejado de deals y clasificación de cierres."""

from .trade_history import (
    build_round_trips,
    points_from_price_delta,
    resolve_exit_cause,
)

__all__ = [
    "build_round_trips",
    "points_from_price_delta",
    "resolve_exit_cause",
]
