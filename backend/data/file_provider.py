# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

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


class FileProvider(IHistoricalDataSource):

    def __init__(self, data_dir: str = "cache/file"):
        self._data_dir = data_dir
        self._symbols = _load_symbols_json()

    def get_rates_df(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        search_dir = os.path.join(self._data_dir, symbol, timeframe)
        if not os.path.isdir(search_dir):
            raise RuntimeError(
                f"No se encontraron datos para {symbol}/{timeframe} en {search_dir}"
            )

        frames = []
        for fname in sorted(os.listdir(search_dir)):
            fpath = os.path.join(search_dir, fname)
            if fname.endswith(".parquet"):
                df = pd.read_parquet(fpath)
            elif fname.endswith(".csv"):
                df = pd.read_csv(fpath)
            else:
                continue
            frames.append(df)

        if not frames:
            raise RuntimeError(
                f"No se encontraron archivos parquet/csv para {symbol}/{timeframe} en {search_dir}"
            )

        combined = pd.concat(frames, ignore_index=True)

        # Normalizar columna time a pd.Timestamp UTC
        if "time" in combined.columns:
            col = combined["time"]
            if pd.api.types.is_integer_dtype(col):
                combined["time"] = pd.to_datetime(col, unit="s", utc=True)
            else:
                combined["time"] = pd.to_datetime(col, utc=True)

        combined = combined.sort_values("time").reset_index(drop=True)

        start_ts = pd.Timestamp(start, tz="UTC") if start.tzinfo is None else pd.Timestamp(start)
        end_ts = pd.Timestamp(end, tz="UTC") if end.tzinfo is None else pd.Timestamp(end)
        mask = (combined["time"] >= start_ts) & (combined["time"] <= end_ts)
        result = combined[mask].reset_index(drop=True)

        if result.empty:
            raise RuntimeError(
                f"Sin datos en el rango [{start}, {end}] para {symbol}/{timeframe}"
            )

        # Garantizar columnas opcionales con valor 0
        for col in ("tick_volume", "spread", "real_volume"):
            if col not in result.columns:
                result[col] = 0

        return result

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
