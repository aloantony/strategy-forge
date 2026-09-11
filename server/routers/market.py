# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""server/routers/market.py — Velas históricas vía IHistoricalDataSource."""

from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, HTTPException

from backend.core import config
from backend.data.factory import build_data_source, resolve_symbol_for_request

router = APIRouter(tags=["market"])


@router.get("/candles")
def get_candles(
    symbol: str = "",
    timeframe: str = "M1",
    start: str = "",
    end: str = "",
    source: str = "mt5",
    limit: int = 5000,
):
    symbol = symbol or str(getattr(config, "SYMBOL", "") or "")
    if not symbol:
        raise HTTPException(status_code=400, detail="Falta el símbolo")
    try:
        start_dt = _parse_date(start)
        end_dt = _parse_date(end, end_of_day=True) if end else datetime.now(timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        data_source = build_data_source(source, symbol)
        request_symbol = resolve_symbol_for_request(source, symbol)
        df = data_source.get_rates_df(request_symbol, timeframe, start_dt, end_dt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudieron obtener velas: {exc}")

    if df is None or df.empty:
        return {"symbol": symbol, "timeframe": timeframe, "candles": []}

    df = df.sort_values("time").tail(max(1, int(limit)))
    times = pd.to_datetime(df["time"], utc=True).astype("int64") // 10**9
    candles = [
        {
            "time": int(t),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(getattr(row, "tick_volume", 0) or 0),
        }
        for t, row in zip(times, df.itertuples(index=False))
    ]
    return {"symbol": symbol, "timeframe": timeframe, "candles": candles}


def _parse_date(value: str, end_of_day: bool = False) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Fecha requerida (YYYY-MM-DD)")
    base = datetime.strptime(text, "%Y-%m-%d")
    if end_of_day:
        base = base.replace(hour=23, minute=59, second=59)
    return base.replace(tzinfo=timezone.utc)
