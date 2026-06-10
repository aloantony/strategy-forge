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

from fastapi import FastAPI

from backend.brokers.factory import build_broker_adapter
from server.routers import account, backtest, market, strategies
from server.ws import router as ws_router


def create_app(broker_name: str = None) -> FastAPI:
    requested_broker = broker_name or os.environ.get("TRADING_BROKER") or None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.broker = build_broker_adapter(requested_broker)
        yield

    app = FastAPI(title="trading-agent server", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "broker": type(getattr(app.state, "broker", None)).__name__,
        }

    app.include_router(strategies.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(backtest.router, prefix="/api")
    app.include_router(market.router, prefix="/api")
    app.include_router(ws_router)
    return app


app = create_app()
