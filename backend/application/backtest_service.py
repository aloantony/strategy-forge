"""Backtest application service.

This module owns backtest request validation and construction so UI callers do
not need to know how data sources, canonical symbols, dates, and runtime
requests fit together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from backend.core import config
from backend.backtesting import run_backtest, run_backtest_comparison
from backend.data.factory import build_data_source, resolve_symbol_for_request


@dataclass
class BacktestPreparedRun:
    request: dict
    data_source: Any
    form: dict


@dataclass
class BacktestPreparedComparison:
    request: dict
    data_source: Any


class BacktestService:
    """Prepare and execute backtests independently from any UI framework."""

    def __init__(
        self,
        *,
        config_module=config,
        data_source_factory: Callable[[str, str], Any] = build_data_source,
        symbol_resolver: Callable[[str, str], str] = resolve_symbol_for_request,
        run_backtest_func: Callable[..., dict] = run_backtest,
        run_comparison_func: Callable[..., dict] = run_backtest_comparison,
        local_tz=None,
    ):
        self._config = config_module
        self._data_source_factory = data_source_factory
        self._symbol_resolver = symbol_resolver
        self._run_backtest = run_backtest_func
        self._run_comparison = run_comparison_func
        self._local_tz = local_tz

    @staticmethod
    def dukascopy_available() -> bool:
        try:
            from dukascopy_python import fetch  # noqa: F401
            return True
        except ImportError:
            return False

    def parse_date(self, value: str, *, end_of_day: bool = False) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Las fechas del backtest son obligatorias")
        base = datetime.strptime(text, "%Y-%m-%d")
        if end_of_day:
            base = base.replace(hour=23, minute=59, second=59)
        local_tz = self._local_tz or datetime.now().astimezone().tzinfo or timezone.utc
        return base.replace(tzinfo=local_tz).astimezone(timezone.utc)

    def prepare_run(self, payload: dict, strategy_entry: dict) -> BacktestPreparedRun:
        if not isinstance(payload, dict):
            raise ValueError("Payload de backtest inválido")
        entry = self._require_strategy_entry(strategy_entry)

        symbol = str(payload.get("symbol") or "").strip()
        if not symbol:
            raise ValueError("Debe seleccionar un símbolo")

        initial_balance = self._parse_positive_float(
            payload.get("initial_balance"),
            "El balance inicial debe ser mayor que cero",
        )
        start_date = self.parse_date(payload.get("start_date"), end_of_day=False)
        end_date = self.parse_date(payload.get("end_date"), end_of_day=True)
        if end_date < start_date:
            raise ValueError("La fecha fin no puede ser anterior a la fecha inicio")

        source_name = self._normalize_source_name(payload.get("data_source"))
        data_source = self._data_source_factory(source_name, symbol)
        request_symbol = self._symbol_resolver(source_name, symbol)

        form = {
            "strategy_key": entry["key"],
            "symbol": symbol,
            "preset": str(payload.get("preset") or "CUSTOM").upper(),
            "start_date": str(payload.get("start_date") or ""),
            "end_date": str(payload.get("end_date") or ""),
            "initial_balance": f"{initial_balance:.2f}",
            "data_source": source_name,
        }

        request = {
            "strategy_key": entry["key"],
            "strategy_label": entry["label"],
            "module": entry.get("module_obj"),
            "symbol": request_symbol,
            "data_provider": source_name,
            "timeframe_value": entry.get("timeframe_value"),
            "start_date": start_date,
            "end_date": end_date,
            "initial_balance": initial_balance,
            "warmup_bars": self._warmup_bars(),
            "lot": self._float_config("LOT", 0.01),
            "sl_points": self._float_config("SL_POINTS", 0.0),
            "tp_points": self._float_config("TP_POINTS", 0.0),
        }
        return BacktestPreparedRun(request=request, data_source=data_source, form=form)

    def prepare_comparison(
        self,
        payload: dict,
        strategy_entries: list[dict],
    ) -> BacktestPreparedComparison:
        if not isinstance(payload, dict):
            raise ValueError("Payload de comparación inválido")

        if len(strategy_entries) < 2:
            raise ValueError("Se requieren al menos 2 estrategias para comparar")

        strategies = []
        for raw_entry in strategy_entries:
            entry = self._require_strategy_entry(raw_entry)
            strategies.append({
                "strategy_key": entry["key"],
                "strategy_label": entry["label"],
                "module": entry.get("module_obj"),
                "timeframe_value": entry.get("timeframe_value"),
            })

        symbol = str(payload.get("symbol") or "").strip()
        if not symbol:
            raise ValueError("Debe seleccionar un símbolo")

        initial_balance = self._parse_positive_float(
            payload.get("initial_balance"),
            "El balance inicial debe ser mayor que cero",
        )
        start_date = self.parse_date(payload.get("start_date"), end_of_day=False)
        end_date = self.parse_date(payload.get("end_date"), end_of_day=True)
        if end_date < start_date:
            raise ValueError("La fecha fin no puede ser anterior a la fecha inicio")

        source_name = self._normalize_source_name(payload.get("data_source"))
        data_source = self._data_source_factory(source_name, symbol)
        request_symbol = self._symbol_resolver(source_name, symbol)

        request = {
            "symbol": request_symbol,
            "data_provider": source_name,
            "start_date": start_date,
            "end_date": end_date,
            "initial_balance": initial_balance,
            "strategies": strategies,
            "warmup_bars": self._warmup_bars(),
            "lot": self._float_config("LOT", 0.01),
            "sl_points": self._float_config("SL_POINTS", 0.0),
            "tp_points": self._float_config("TP_POINTS", 0.0),
        }
        return BacktestPreparedComparison(request=request, data_source=data_source)

    def execute_run(self, request: dict, data_source=None) -> dict:
        try:
            return self._run_backtest(request, data_source=data_source)
        except Exception as error:
            return {"status": "error", "error": str(error)}

    def execute_comparison(self, request: dict, data_source=None) -> dict:
        try:
            return self._run_comparison(request, data_source=data_source)
        except Exception as error:
            return {"status": "error", "error": str(error)}

    def _require_strategy_entry(self, entry: dict) -> dict:
        if not isinstance(entry, dict):
            raise ValueError("Estrategia de backtest no encontrada")
        if entry.get("module_obj") is None:
            raise ValueError("No se pudo cargar la estrategia para backtest")
        return entry

    def _normalize_source_name(self, value) -> str:
        source_name = str(value or "mt5").strip().lower()
        return source_name if source_name in ("mt5", "dukascopy") else "mt5"

    @staticmethod
    def _parse_positive_float(value, message: str) -> float:
        try:
            parsed = float(value or 0.0)
        except Exception:
            parsed = 0.0
        if parsed <= 0:
            raise ValueError(message)
        return parsed

    def _warmup_bars(self) -> int:
        return max(int(getattr(self._config, "BARS_HISTORY", 500) or 500), 500)

    def _float_config(self, key: str, default: float) -> float:
        return float(getattr(self._config, key, default) or default)

