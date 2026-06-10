from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.brokers.interface import InstrumentInfo


class IDataFeed(ABC):
    """
    Fuente de datos para el runtime en vivo.

    Responsabilidad: dado un símbolo y timeframe, retorna un DataFrame ya
    completamente enriquecido — equivalente al resultado de:
        data_feed.get_rates_df() +
        add_source_columns() + add_baseline_bands() + add_supertrend() + add_tci()

    El consumidor (main.py, gui_charts.py) no necesita aplicar ninguna
    transformación adicional; recibe el DataFrame listo para estrategias.
    """

    @abstractmethod
    def get_enriched_df(
        self,
        symbol: str,       # símbolo tal como lo conoce el broker/feed (e.g. "#Germany40")
        timeframe: str,    # "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1"
        bars: int,         # número de velas a obtener (típicamente config.BARS_HISTORY = 500)
    ) -> pd.DataFrame:
        # Retorna DataFrame con columnas mínimas:
        #   time             pd.Timestamp (tz=UTC), ordenado ASC
        #   open, high, low, close, tick_volume  (tipos MT5 habituales)
        #   OHLC4, HLC3, HL2, CLOSE, h_set, l_set  (de add_source_columns)
        #   average, upper, lower, atr              (de add_baseline_bands)
        #   supertrend, supertrend_dir, supertrend_up, supertrend_down  (de add_supertrend)
        #   tci, tci_signal, tci_hist               (de add_tci)
        # Nunca retorna None — lanza RuntimeError si no hay datos.
        ...


class IHistoricalDataSource(ABC):

    @abstractmethod
    def get_rates_df(
        self,
        symbol: str,           # símbolo canónico (e.g. "GER40", "EURUSD")
        timeframe: str,        # "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1"
        start: datetime,       # UTC; incluir warmup (ya calculado por el caller)
        end: datetime,         # UTC; inclusive
    ) -> pd.DataFrame:
        # Retorna DataFrame con columnas:
        #   time       pd.Timestamp (tz=UTC)
        #   open       float64
        #   high       float64
        #   low        float64
        #   close      float64
        #   tick_volume int64  (0 si no disponible)
        #   spread     int64  (0 si no disponible)
        #   real_volume int64  (0 si no disponible)
        # Ordenado por time ASC. Nunca retorna None — lanza RuntimeError si sin datos.
        ...

    @abstractmethod
    def get_instrument_info(
        self,
        symbol: str,           # símbolo canónico
    ) -> Optional[InstrumentInfo]:
        # Retorna InstrumentInfo para el símbolo. None si no conocido.
        # Fuentes: symbols.json (proveedores sin MT5) o MT5 directamente (MT5Provider).
        ...
