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
