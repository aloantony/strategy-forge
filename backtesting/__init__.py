"""
Paquete de backtesting.
"""

from .runtime import BacktestEngine, BacktestRequest, run_backtest, run_backtest_comparison

__all__ = ["BacktestEngine", "BacktestRequest", "run_backtest", "run_backtest_comparison"]
