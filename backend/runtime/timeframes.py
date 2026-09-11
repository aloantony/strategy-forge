# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""Shared timeframe catalogue and OHLCV resampling helpers."""

from __future__ import annotations

from typing import Any

TIMEFRAME_MINUTES = {
    "M1": 1,
    "M2": 2,
    "M3": 3,
    "M5": 5,
    "M10": 10,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

# Valores numéricos del enum TIMEFRAME_* de MetaTrader5 (parte estable de su API).
# Hardcodeados para que el runtime sea broker-agnóstico: esta capa no importa mt5.
TIMEFRAME_MAP = {
    "M1": 1,
    "M2": 2,
    "M3": 3,
    "M5": 5,
    "M10": 10,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}

TIMEFRAME_SECONDS = {label: minutes * 60 for label, minutes in TIMEFRAME_MINUTES.items()}
SYNTHETIC_FROM_M1 = {"M2", "M3", "M10"}


def normalize_timeframe_label(value: Any) -> str:
    if value is None:
        return ""
    label = str(value).strip().upper()
    return label if label in TIMEFRAME_MINUTES else ""


def resolve_timeframe_value(value: Any):
    if value is None:
        return None
    if isinstance(value, str):
        return TIMEFRAME_MAP.get(value.strip().upper())
    if isinstance(value, int) and value in TIMEFRAME_MAP.values():
        return value
    return None


def timeframe_label(timeframe_value: int) -> str:
    reverse_map = {v: k for k, v in TIMEFRAME_MAP.items()}
    return reverse_map.get(timeframe_value, "")


def timeframe_to_minutes(value: Any, default: int = 1) -> int:
    if isinstance(value, int):
        label = timeframe_label(value)
    else:
        label = normalize_timeframe_label(value)
    return int(TIMEFRAME_MINUTES.get(label, default))


def timeframe_to_seconds(timeframe_value: int) -> int:
    label = timeframe_label(timeframe_value)
    return int(TIMEFRAME_SECONDS.get(label, 60))


def lowest_timeframe_label(labels: list[str] | tuple[str, ...] | set[str]) -> str:
    normalized = [normalize_timeframe_label(label) for label in labels]
    normalized = [label for label in normalized if label]
    if not normalized:
        return "M1"
    return min(normalized, key=lambda label: TIMEFRAME_MINUTES[label])

