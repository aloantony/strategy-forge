"""
server/app.py — Aplicación FastAPI del trading-agent.

Expone el backend (broker-agnóstico) como API REST + WebSocket para que distintos
frontends (desktop, web, móvil) se conecten al mismo servidor.

Arranque:
    uvicorn server.app:app --host 0.0.0.0 --port 8000

El broker se selecciona vía backend.brokers.factory (config.BROKER o env TRADING_BROKER:
"mt5" | "paper" | "auto"). En Linux/sin MT5 el default automático es paper.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.application.backtest_service import BacktestService
from backend.brokers.factory import build_broker_adapter
from backend.core import config
from backend.runtime.timeframes import TIMEFRAME_MINUTES
from server.routers import account, backtest, builder, market, strategies
from server.ws import router as ws_router

_WEB_DIR = Path(__file__).resolve().parents[1] / "frontend" / "web"


def create_app(broker_name: str = None) -> FastAPI:
    requested_broker = broker_name or os.environ.get("TRADING_BROKER") or None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.broker = build_broker_adapter(requested_broker)
        if type(app.state.broker).__name__ == "MT5BrokerAdapter":
            # El terminal MT5 requiere initialize() por proceso (la GUI lo hacía en su arranque).
            from backend.brokers.mt5.connection import initialize_mt5
            initialize_mt5()
        yield

    app = FastAPI(title="trading-agent server", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "broker": type(getattr(app.state, "broker", None)).__name__,
        }

    @app.get("/api/meta")
    def meta():
        return {
            "symbol_default": str(getattr(config, "SYMBOL", "") or ""),
            "timeframes": list(TIMEFRAME_MINUTES),
            "timeframe_minutes": dict(TIMEFRAME_MINUTES),
            "data_sources": ["mt5", "dukascopy"],
            "dukascopy_available": BacktestService.dukascopy_available(),
        }

    app.include_router(strategies.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(backtest.router, prefix="/api")
    app.include_router(builder.router, prefix="/api")
    app.include_router(market.router, prefix="/api")
    app.include_router(ws_router)

    # Frontend web estático (al final: /api y /ws tienen prioridad de ruta).
    if _WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
    return app


app = create_app()
