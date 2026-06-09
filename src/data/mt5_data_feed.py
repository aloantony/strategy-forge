from src.mt5_import import mt5

import data_feed as _data_feed
from src.data.interface import IDataFeed

TIMEFRAME_INT = {
    "M1": 1, "M2": 2, "M3": 3, "M5": 5, "M10": 10, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408,
}


class MT5DataFeed(IDataFeed):
    """
    Implementación concreta de IDataFeed que envuelve data_feed.py del runtime actual.
    Toda la cadena add_* se aplica internamente; el caller recibe el DataFrame enriquecido.
    Los parámetros de indicadores se reciben en el constructor para no importar config
    desde la interfaz.
    """

    def __init__(
        self,
        source_mode: str,
        ma_length: int,
        atr_length: int,
        atr_mult: float,
        supertrend_atr_length: int,
        supertrend_mult: float,
        supertrend_source: str,
        supertrend_use_hma: bool,
        hma_length: int,
        tci_fast: int,
        tci_slow: int,
        tci_signal: int,
    ):
        self._source_mode = source_mode
        self._ma_length = ma_length
        self._atr_length = atr_length
        self._atr_mult = atr_mult
        self._supertrend_atr_length = supertrend_atr_length
        self._supertrend_mult = supertrend_mult
        self._supertrend_source = supertrend_source
        self._supertrend_use_hma = supertrend_use_hma
        self._hma_length = hma_length
        self._tci_fast = tci_fast
        self._tci_slow = tci_slow
        self._tci_signal = tci_signal

    def get_enriched_df(self, symbol: str, timeframe: str, bars: int):
        tf_int = TIMEFRAME_INT[timeframe]
        df = _data_feed.get_rates_df(symbol, tf_int, bars)
        df = _data_feed.add_source_columns(df, self._source_mode)
        df = _data_feed.add_baseline_bands(df, self._ma_length, self._atr_length, self._atr_mult)
        df = _data_feed.add_supertrend(
            df,
            atr_length=self._supertrend_atr_length,
            atr_mult=self._supertrend_mult,
            source_col=self._supertrend_source,
            use_hma=self._supertrend_use_hma,
            hma_length=self._hma_length,
        )
        df = _data_feed.add_tci(
            df,
            fast_length=self._tci_fast,
            slow_length=self._tci_slow,
            signal_length=self._tci_signal,
        )
        return df
