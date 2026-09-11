# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""server/routers/account.py — Cuenta y posiciones vía IBrokerAdapter."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from backend.core import config
from server.schemas import AccountResponse

router = APIRouter(tags=["account"])


@router.get("/account", response_model=AccountResponse)
def get_account(request: Request):
    info = request.app.state.broker.get_account_info()
    if info is None:
        raise HTTPException(status_code=503, detail="Cuenta no disponible (broker sin conexión)")
    return asdict(info)


@router.get("/positions")
def get_positions(request: Request, symbol: str = "", magic: int = 0):
    broker = request.app.state.broker
    symbol = symbol or str(getattr(config, "SYMBOL", "") or "")
    return {
        "symbol": symbol,
        "magic": magic,
        "positions": broker.get_open_positions(symbol, magic),
    }


@router.get("/market-status")
def market_status(request: Request, symbol: str = ""):
    symbol = symbol or str(getattr(config, "SYMBOL", "") or "")
    is_open, detail = request.app.state.broker.is_market_open(symbol)
    return {"symbol": symbol, "open": is_open, "detail": detail}
