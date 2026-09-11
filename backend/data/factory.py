# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Data source factory for the backtest engine.

Provides:
  - build_data_source(source_name, symbol_mt5) -> IHistoricalDataSource
  - resolve_canonical_symbol(symbol_mt5) -> str | None
  - resolve_symbol_for_request(source_name, symbol_mt5) -> str

Does NOT import config — receives all parameters from the caller.
"""

import json
import logging
import os
from typing import Optional

from backend.data.interface import IHistoricalDataSource

logger = logging.getLogger(__name__)

_SYMBOLS_JSON = os.path.join(os.path.dirname(__file__), "symbols.json")


def _load_symbols_json() -> dict:
    """Load symbols.json. Returns {} if the file cannot be read."""
    try:
        with open(_SYMBOLS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("No se pudo leer symbols.json desde %s", _SYMBOLS_JSON)
        return {}


def resolve_canonical_symbol(symbol_mt5: str) -> Optional[str]:
    """
    Translate a GUI / MT5-format symbol to the canonical key in symbols.json.

    Strategy:
    1. Direct lookup: if symbol_mt5 is already a canonical key (e.g. "EURUSD"),
       return it immediately.
    2. Inverse scan: iterate entries comparing providers["mt5"] to symbol_mt5.

    Returns None if the symbol cannot be resolved.
    """
    symbols = _load_symbols_json()

    # Direct lookup: symbol already is the canonical key
    if symbol_mt5 in symbols:
        return symbol_mt5

    # Inverse lookup: MT5 ticker → canonical key
    for canonical_key, entry in symbols.items():
        mt5_ticker = entry.get("providers", {}).get("mt5", "")
        if mt5_ticker == symbol_mt5:
            return canonical_key

    return None


def resolve_symbol_for_request(source_name: str, symbol_mt5: str) -> str:
    """
    Return the symbol string that should be placed in request["symbol"] for the
    BacktestEngine.

    - "mt5": the MT5 symbol is passed as-is; MT5HistoricalDataSource resolves
      it internally.
    - "dukascopy": the canonical symbol is required by DukascopyHistoricalDataSource.
    - Any other value: falls back to symbol_mt5 unchanged.

    Raises ValueError if source_name == "dukascopy" and the symbol cannot be
    resolved (should not happen if build_data_source was called first).
    """
    if source_name == "mt5":
        return symbol_mt5

    if source_name == "dukascopy":
        canonical = resolve_canonical_symbol(symbol_mt5)
        if canonical is None:
            raise ValueError(
                f"No se pudo resolver símbolo canónico para '{symbol_mt5}'"
            )
        return canonical

    # Unknown source — return MT5 symbol unchanged as a safe default
    return symbol_mt5


def build_data_source(source_name: str, symbol_mt5: str) -> IHistoricalDataSource:
    """
    Instantiate and return the concrete IHistoricalDataSource for the given
    source_name and symbol.

    Parameters
    ----------
    source_name : str
        Data source identifier: "mt5" or "dukascopy".
    symbol_mt5 : str
        Symbol in GUI / MT5 format (e.g. "#Germany40", "EURUSD").

    Returns
    -------
    IHistoricalDataSource
        Ready-to-use instance.

    Raises
    ------
    ValueError
        If source_name is not recognised, if the symbol has no entry in
        symbols.json for the requested source, or if a required package is not
        installed.
    """
    if source_name == "mt5":
        # MT5HistoricalDataSource accepts the MT5 symbol directly in get_rates_df;
        # no symbol validation is needed here.
        from backend.data.mt5_historical_source import MT5HistoricalDataSource
        return MT5HistoricalDataSource()

    elif source_name == "dukascopy":
        # Verify that dukascopy-python is installed before attempting to instantiate.
        try:
            from dukascopy_python import fetch as _check  # noqa: F401
        except ImportError:
            raise ValueError(
                "dukascopy-python no está instalado. "
                "Ejecuta: pip install 'dukascopy-python>=4.0.1'"
            )

        # Resolve MT5 symbol → canonical key
        canonical = resolve_canonical_symbol(symbol_mt5)
        if canonical is None:
            raise ValueError(
                f"El símbolo '{symbol_mt5}' no tiene entrada en symbols.json. "
                "No se puede usar Dukascopy con este símbolo."
            )

        # Verify the canonical symbol has a dukascopy provider entry
        symbols = _load_symbols_json()
        dk_ticker = symbols[canonical].get("providers", {}).get("dukascopy")
        if not dk_ticker:
            raise ValueError(
                f"El símbolo '{symbol_mt5}' (canónico: '{canonical}') "
                "no tiene proveedor Dukascopy configurado en symbols.json."
            )

        from backend.data.dukascopy_historical_source import DukascopyHistoricalDataSource
        return DukascopyHistoricalDataSource()

    else:
        raise ValueError(
            f"Fuente de datos no reconocida: '{source_name}'. "
            "Valores válidos: 'mt5', 'dukascopy'"
        )
