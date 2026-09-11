# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""server/routers/backtest.py — Ejecución de backtests vía BacktestService."""

from fastapi import APIRouter, HTTPException

from backend.application import strategy_catalog
from backend.application.backtest_service import BacktestService
from server.schemas import BacktestRunRequest

router = APIRouter(tags=["backtest"])

_service = BacktestService()


@router.post("/backtest/run")
def run_backtest(payload: BacktestRunRequest):
    entry = strategy_catalog.load_strategy_entry(payload.strategy_key)
    if entry is None:
        raise HTTPException(status_code=404,
                            detail=f"Estrategia no encontrada: {payload.strategy_key}")
    try:
        prepared = _service.prepare_run(payload.model_dump(), entry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Endpoint sync: FastAPI lo ejecuta en threadpool, no bloquea el event loop.
    result = _service.execute_run(prepared.request, data_source=prepared.data_source)
    return result
