# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
backend/brokers/factory.py — Selección del adaptador de broker por configuración.

Regla: el core/servidor no importa MT5 directamente; pide aquí un IBrokerAdapter.
- config.BROKER = "mt5" | "paper" (opcional).
- Sin config: "auto" → MT5 si el paquete está disponible (Windows), si no paper.
"""

from backend.core import config
from backend.brokers.interface import IBrokerAdapter


def build_broker_adapter(name: str = None) -> IBrokerAdapter:
    requested = (name or getattr(config, "BROKER", "") or "auto").strip().lower()

    if requested == "paper":
        return _build_paper()
    if requested == "mt5":
        return _build_mt5()
    if requested == "auto":
        from backend.brokers.mt5_import import mt5
        return _build_mt5() if mt5 is not None else _build_paper()
    raise ValueError(f"Broker desconocido: '{requested}' (usa 'mt5', 'paper' o 'auto')")


def _build_mt5() -> IBrokerAdapter:
    # Import perezoso: solo se toca MT5 si se pide explícitamente o está disponible.
    from backend.brokers.mt5.adapter import MT5BrokerAdapter
    return MT5BrokerAdapter()


def _build_paper() -> IBrokerAdapter:
    from backend.brokers.paper import PaperBrokerAdapter
    return PaperBrokerAdapter(
        initial_balance=float(getattr(config, "PAPER_INITIAL_BALANCE", 10_000.0)),
    )
