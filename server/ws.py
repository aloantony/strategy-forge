# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
server/ws.py — Stream en vivo por WebSocket.

/ws/stream — push periódico de estado: cuenta, posiciones y mercado. Los
frontends (desktop/web) se suscriben aquí en lugar de hacer polling.

Mensaje:
    {"type": "snapshot", "ts": <epoch>, "account": {...}|null,
     "positions": [...], "market": {"symbol": ..., "open": bool, "detail": str}}
"""

import asyncio
import time
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core import config

router = APIRouter()

STREAM_INTERVAL_SECONDS = 2.0


def _snapshot(broker, symbol: str, magic: int) -> dict:
    account = broker.get_account_info()
    is_open, detail = broker.is_market_open(symbol)
    return {
        "type": "snapshot",
        "ts": int(time.time()),
        "account": asdict(account) if account is not None else None,
        "positions": broker.get_open_positions(symbol, magic),
        "market": {"symbol": symbol, "open": is_open, "detail": detail},
    }


@router.websocket("/ws/stream")
async def stream(websocket: WebSocket):
    await websocket.accept()
    broker = websocket.app.state.broker
    symbol = str(websocket.query_params.get("symbol") or getattr(config, "SYMBOL", "") or "")
    magic = int(websocket.query_params.get("magic") or 0)
    try:
        while True:
            # Las llamadas al broker son bloqueantes: fuera del event loop.
            payload = await asyncio.to_thread(_snapshot, broker, symbol, magic)
            await websocket.send_json(payload)
            await asyncio.sleep(STREAM_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        pass
