import json
import logging
import os
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.brokers.interface import InstrumentInfo
from backend.data.interface import IHistoricalDataSource

try:
    from dukascopy_python import fetch as dukascopy_fetch
except ImportError:
    dukascopy_fetch = None

logger = logging.getLogger(__name__)

_SYMBOLS_JSON = os.path.join(os.path.dirname(__file__), "symbols.json")

_TIMEFRAME_MAP = {
    "M1": "1MIN", "M5": "5MIN", "M15": "15MIN", "M30": "30MIN",
    "H1": "1HOUR", "H4": "4HOUR", "D1": "1DAY",
}


def _load_symbols_json() -> dict:
    try:
        with open(_SYMBOLS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class DukascopyHistoricalDataSource(IHistoricalDataSource):
    """
    Implementación de IHistoricalDataSource que descarga datos OHLCV
    históricos de Dukascopy via dukascopy-python.

    La resolución de símbolo canónico → símbolo Dukascopy se hace
    leyendo providers["dukascopy"] de src/data/symbols.json.
    """

    def __init__(self) -> None:
        self._symbols = _load_symbols_json()

    def get_rates_df(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        if dukascopy_fetch is None:
            raise RuntimeError(
                "dukascopy-python no está instalado. "
                "Ejecuta: pip install 'dukascopy-python>=4.0.1'"
            )

        entry = self._symbols.get(symbol)
        if entry is None:
            raise ValueError(
                f"Símbolo canónico '{symbol}' no encontrado en symbols.json"
            )

        dk_symbol = entry.get("providers", {}).get("dukascopy")
        if dk_symbol is None:
            raise ValueError(
                f"Sin proveedor 'dukascopy' configurado para '{symbol}' en symbols.json"
            )

        dk_timeframe = _TIMEFRAME_MAP.get(timeframe)
        if dk_timeframe is None:
            raise ValueError(f"Timeframe no soportado: '{timeframe}'")

        logger.debug(
            "Descargando %s (%s) [%s] %s → %s",
            symbol, dk_symbol, timeframe, start, end,
        )

        df = dukascopy_fetch(
            instrument=dk_symbol,
            interval=dk_timeframe,
            offer_side="bid",
            start=start,
            end=end,
        )

        if df is None or df.empty:
            raise RuntimeError(
                f"No se obtuvieron datos para {symbol} [{timeframe}] "
                f"entre {start} y {end}"
            )

        # Adaptar schema: índice "timestamp" → columna "time"
        df = df.reset_index().rename(columns={"timestamp": "time"})

        # Garantizar timezone UTC en columna time
        if df["time"].dt.tz is None:
            df["time"] = df["time"].dt.tz_localize("UTC")
        else:
            df["time"] = df["time"].dt.tz_convert("UTC")

        # Mapear volume (float64) → tick_volume (int64)
        df = df.rename(columns={"volume": "tick_volume"})
        df["tick_volume"] = df["tick_volume"].round().astype("int64")

        # Dukascopy no provee spread ni real_volume — rellenar con 0
        df["spread"] = pd.array([0] * len(df), dtype="int64")
        df["real_volume"] = pd.array([0] * len(df), dtype="int64")

        df = df[["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]]
        df = df.sort_values("time").reset_index(drop=True)

        return df

    def get_instrument_info(self, symbol: str) -> Optional[InstrumentInfo]:
        entry = self._symbols.get(symbol)
        if entry is None:
            return None
        inst = entry.get("instrument", {})
        return InstrumentInfo(
            symbol=symbol,
            tick_size=float(inst.get("tick_size", 0.0)),
            tick_value=float(inst.get("tick_value", 0.0)),
            point=float(inst.get("point", 0.0)),
            digits=int(inst.get("digits", 0)),
            volume_min=float(inst.get("volume_min", 0.01)),
            volume_max=float(inst.get("volume_max", 100.0)),
            volume_step=float(inst.get("volume_step", 0.01)),
            volume_digits=int(inst.get("volume_digits", 2)),
            trade_stops_level=int(inst.get("trade_stops_level", 0)),
            trade_freeze_level=int(inst.get("trade_freeze_level", 0)),
            trade_fillings=int(inst.get("trade_fillings", 1)),
            filling_mode=int(inst.get("filling_mode", 1)),
            trade_exemode=int(inst.get("trade_exemode", 0)),
        )
