import json
import os
from datetime import datetime
from typing import Optional

from backend.brokers.mt5_import import mt5

import pandas as pd

from backend.brokers.interface import InstrumentInfo
from backend.data.interface import IHistoricalDataSource

TIMEFRAME_INT = {
    "M1": 1, "M2": 2, "M3": 3, "M5": 5, "M10": 10, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408,
}

_SYMBOLS_JSON = os.path.join(os.path.dirname(__file__), "symbols.json")


def _load_symbols_json() -> dict:
    try:
        with open(_SYMBOLS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class MT5HistoricalDataSource(IHistoricalDataSource):

    def _resolve_mt5_symbol(self, symbol: str) -> str:
        symbols = _load_symbols_json()
        entry = symbols.get(symbol)
        if entry is not None:
            return entry.get("providers", {}).get("mt5", symbol)
        return symbol

    def get_rates_df(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 no está disponible")
        tf_int = TIMEFRAME_INT[timeframe]
        mt5_symbol = self._resolve_mt5_symbol(symbol)
        rates = mt5.copy_rates_range(mt5_symbol, tf_int, start, end)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No se pudieron obtener datos para {symbol}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df.sort_values("time").reset_index(drop=True)

    def get_instrument_info(self, symbol: str) -> Optional[InstrumentInfo]:
        if mt5 is None:
            return None
        mt5_symbol = self._resolve_mt5_symbol(symbol)
        info = mt5.symbol_info(mt5_symbol)
        if info is None:
            return None
        return InstrumentInfo(
            symbol=symbol,
            tick_size=float(info.trade_tick_size),
            tick_value=float(info.trade_tick_value),
            point=float(info.point),
            digits=int(info.digits),
            volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),
            volume_step=float(info.volume_step),
            volume_digits=int(getattr(info, "volume_digits", 2)),
            trade_stops_level=int(info.trade_stops_level),
            trade_freeze_level=int(info.trade_freeze_level),
            trade_fillings=int(getattr(info, "trade_fillings", 1)),
            filling_mode=int(getattr(info, "filling_mode", 1)),
            trade_exemode=int(info.trade_exemode),
        )
