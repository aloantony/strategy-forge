"""
Paquete de backtesting.
"""

from .runtime import BacktestEngine, BacktestRequest, run_backtest

__all__ = ["BacktestEngine", "BacktestRequest", "run_backtest"]
