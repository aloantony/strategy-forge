# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Tests para DukascopyHistoricalDataSource.

No requieren MT5 instalado ni conexión de red real.
dukascopy_python.fetch se mockea en todos los tests que llaman a get_rates_df.
"""
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.data.dukascopy_historical_source import DukascopyHistoricalDataSource

START = datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc)
END = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)


def _mock_fetch_df(n: int = 5) -> pd.DataFrame:
    """Simula el output de dukascopy_python.fetch() para un intervalo OHLC."""
    timestamps = pd.date_range("2024-01-02 09:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "open":   np.array([16000.0, 16010.0, 16005.0, 16020.0, 16015.0][:n]),
            "high":   np.array([16050.0, 16060.0, 16055.0, 16070.0, 16065.0][:n]),
            "low":    np.array([15980.0, 15990.0, 15985.0, 16000.0, 15995.0][:n]),
            "close":  np.array([16010.0, 16005.0, 16020.0, 16015.0, 16025.0][:n]),
            "volume": np.array([500.0, 600.0, 550.0, 700.0, 650.0][:n]),
        },
        index=pd.Index(timestamps, name="timestamp"),
    )


# ---------------------------------------------------------------------------
# Contrato de columnas
# ---------------------------------------------------------------------------

@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_columns_exact(mock_fetch):
    mock_fetch.return_value = _mock_fetch_df()
    df = DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)
    assert list(df.columns) == [
        "time", "open", "high", "low", "close",
        "tick_volume", "spread", "real_volume",
    ]


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------

@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_dtypes(mock_fetch):
    mock_fetch.return_value = _mock_fetch_df()
    df = DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)
    assert df["open"].dtype == np.float64
    assert df["high"].dtype == np.float64
    assert df["low"].dtype == np.float64
    assert df["close"].dtype == np.float64
    assert df["tick_volume"].dtype == np.int64
    assert df["spread"].dtype == np.int64
    assert df["real_volume"].dtype == np.int64


# ---------------------------------------------------------------------------
# Columna time — timezone UTC
# ---------------------------------------------------------------------------

@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_time_has_utc_timezone(mock_fetch):
    mock_fetch.return_value = _mock_fetch_df()
    df = DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)
    assert df["time"].dt.tz is not None
    assert str(df["time"].dt.tz) == "UTC"


@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_time_naive_input_gets_localized(mock_fetch):
    """Si dukascopy devuelve timestamps sin tz, el adapter los localiza a UTC."""
    timestamps = pd.date_range("2024-01-02 09:00", periods=3, freq="1min")  # sin tz
    df_raw = pd.DataFrame(
        {
            "open": [16000.0, 16010.0, 16005.0],
            "high": [16050.0, 16060.0, 16055.0],
            "low":  [15980.0, 15990.0, 15985.0],
            "close":[16010.0, 16005.0, 16020.0],
            "volume": [500.0, 600.0, 550.0],
        },
        index=pd.Index(timestamps, name="timestamp"),
    )
    mock_fetch.return_value = df_raw
    df = DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)
    assert str(df["time"].dt.tz) == "UTC"


# ---------------------------------------------------------------------------
# Orden ASC por time
# ---------------------------------------------------------------------------

@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_sorted_ascending_by_time(mock_fetch):
    mock_fetch.return_value = _mock_fetch_df().iloc[::-1]  # devolver en orden inverso
    df = DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)
    assert df["time"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# tick_volume / spread / real_volume
# ---------------------------------------------------------------------------

@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_tick_volume_nonnegative(mock_fetch):
    mock_fetch.return_value = _mock_fetch_df()
    df = DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)
    assert (df["tick_volume"] >= 0).all()


@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_spread_zero(mock_fetch):
    mock_fetch.return_value = _mock_fetch_df()
    df = DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)
    assert (df["spread"] == 0).all()


@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_real_volume_zero(mock_fetch):
    mock_fetch.return_value = _mock_fetch_df()
    df = DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)
    assert (df["real_volume"] == 0).all()


@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_volume_mapped_to_tick_volume(mock_fetch):
    """Verifica que el campo 'volume' de Dukascopy se mapea correctamente a tick_volume."""
    mock_fetch.return_value = _mock_fetch_df(n=3)
    df = DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)
    assert list(df["tick_volume"]) == [500, 600, 550]


# ---------------------------------------------------------------------------
# Manejo de errores
# ---------------------------------------------------------------------------

@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_unknown_symbol_raises_value_error(mock_fetch):
    with pytest.raises(ValueError, match="no encontrado en symbols.json"):
        DukascopyHistoricalDataSource().get_rates_df("UNKNOWN_XYZ", "M1", START, END)


@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_empty_response_raises_runtime_error(mock_fetch):
    mock_fetch.return_value = pd.DataFrame()
    with pytest.raises(RuntimeError):
        DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)


@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_none_response_raises_runtime_error(mock_fetch):
    mock_fetch.return_value = None
    with pytest.raises(RuntimeError):
        DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)


@patch("backend.data.dukascopy_historical_source.dukascopy_fetch")
def test_unsupported_timeframe_raises_value_error(mock_fetch):
    with pytest.raises(ValueError, match="Timeframe no soportado"):
        DukascopyHistoricalDataSource().get_rates_df("GER40", "TICK", START, END)


def test_no_dukascopy_installed_raises_runtime_error():
    """Si dukascopy_fetch es None (paquete no instalado), debe lanzar RuntimeError."""
    with patch("backend.data.dukascopy_historical_source.dukascopy_fetch", None):
        with pytest.raises(RuntimeError, match="dukascopy-python no está instalado"):
            DukascopyHistoricalDataSource().get_rates_df("GER40", "M1", START, END)


# ---------------------------------------------------------------------------
# get_instrument_info
# ---------------------------------------------------------------------------

def test_get_instrument_info_ger40():
    info = DukascopyHistoricalDataSource().get_instrument_info("GER40")
    assert info is not None
    assert info.symbol == "GER40"
    assert info.tick_size == pytest.approx(0.1)
    assert info.tick_value == pytest.approx(1.0)
    assert info.point == pytest.approx(0.1)
    assert info.digits == 1
    assert info.volume_min == pytest.approx(0.01)
    assert info.volume_max == pytest.approx(100.0)
    assert info.volume_step == pytest.approx(0.01)
    assert info.volume_digits == 2


def test_get_instrument_info_unknown_returns_none():
    result = DukascopyHistoricalDataSource().get_instrument_info("UNKNOWN_XYZ")
    assert result is None


def test_get_instrument_info_eurusd():
    info = DukascopyHistoricalDataSource().get_instrument_info("EURUSD")
    assert info is not None
    assert info.symbol == "EURUSD"
    assert info.digits == 5
