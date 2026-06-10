import json
import os
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.brokers.interface import InstrumentInfo
from backend.data.interface import IHistoricalDataSource

_SYMBOLS_JSON = os.path.join(os.path.dirname(__file__), "symbols.json")


def _load_symbols_json() -> dict:
    try:
        with open(_SYMBOLS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class DukascopyProvider(IHistoricalDataSource):

    def __init__(self, cache_dir: str = "cache/dukascopy"):
        self._cache_dir = cache_dir
        self._symbols = _load_symbols_json()

    def get_rates_df(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        # TODO: implementar descarga real de Dukascopy
        # 1. Traducir símbolo canónico → símbolo Dukascopy via symbols.json
        # 2. Determinar meses requeridos en el rango [start, end]
        # 3. Para cada mes:
        #    a. Comprobar si existe cache/<provider>/<symbol>/<timeframe>/<YYYY-MM>.parquet
        #    b. Si existe → cargar desde parquet
        #    c. Si no existe → descargar de Dukascopy API → guardar en parquet → cargar
        # 4. Concatenar todos los meses → filtrar al rango exacto [start, end]
        # 5. Garantizar columnas: time, open, high, low, close, tick_volume, spread, real_volume
        raise NotImplementedError(
            "DukascopyProvider.get_rates_df no implementado todavía. "
            "Usa MT5HistoricalDataSource o FileProvider."
        )

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
