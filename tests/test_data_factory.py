# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Tests for src/data/factory.py

Verifies:
  - build_data_source("mt5", ...) returns MT5HistoricalDataSource
  - build_data_source("dukascopy", known_symbol) returns DukascopyHistoricalDataSource
  - build_data_source("dukascopy", unknown_symbol) raises ValueError
  - build_data_source("dukascopy", ...) raises ValueError when dukascopy-python missing
  - build_data_source("unknown", ...) raises ValueError
  - resolve_canonical_symbol returns expected values
  - resolve_symbol_for_request returns correct symbol per source
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# resolve_canonical_symbol
# ---------------------------------------------------------------------------

class TestResolveCanonicalSymbol:

    def test_direct_canonical_key(self):
        """EURUSD is already the canonical key — returns it without inverse scan."""
        from backend.data.factory import resolve_canonical_symbol
        result = resolve_canonical_symbol("EURUSD")
        assert result == "EURUSD"

    def test_inverse_lookup_germany40(self):
        """#Germany40 is the MT5 ticker; should resolve to GER40."""
        from backend.data.factory import resolve_canonical_symbol
        result = resolve_canonical_symbol("#Germany40")
        assert result == "GER40"

    def test_unknown_symbol_returns_none(self):
        """A symbol not present in symbols.json returns None."""
        from backend.data.factory import resolve_canonical_symbol
        result = resolve_canonical_symbol("XAUUSD_UNKNOWN_XYZ")
        assert result is None

    def test_empty_symbols_json_returns_none(self):
        """If symbols.json cannot be loaded, returns None."""
        from backend.data import factory
        with patch.object(factory, "_load_symbols_json", return_value={}):
            result = factory.resolve_canonical_symbol("#Germany40")
        assert result is None


# ---------------------------------------------------------------------------
# resolve_symbol_for_request
# ---------------------------------------------------------------------------

class TestResolveSymbolForRequest:

    def test_mt5_returns_mt5_symbol(self):
        from backend.data.factory import resolve_symbol_for_request
        assert resolve_symbol_for_request("mt5", "#Germany40") == "#Germany40"

    def test_dukascopy_returns_canonical(self):
        from backend.data.factory import resolve_symbol_for_request
        assert resolve_symbol_for_request("dukascopy", "#Germany40") == "GER40"

    def test_dukascopy_eurusd(self):
        from backend.data.factory import resolve_symbol_for_request
        assert resolve_symbol_for_request("dukascopy", "EURUSD") == "EURUSD"

    def test_dukascopy_unknown_raises(self):
        from backend.data.factory import resolve_symbol_for_request
        with pytest.raises(ValueError, match="No se pudo resolver"):
            resolve_symbol_for_request("dukascopy", "XAUUSD_UNKNOWN_XYZ")

    def test_unknown_source_returns_mt5_symbol(self):
        """Unknown source_name falls back to MT5 symbol unchanged."""
        from backend.data.factory import resolve_symbol_for_request
        assert resolve_symbol_for_request("file", "#Germany40") == "#Germany40"


# ---------------------------------------------------------------------------
# build_data_source — happy path
# ---------------------------------------------------------------------------

class TestBuildDataSourceValid:

    def test_mt5_source_returns_mt5_instance(self):
        from backend.data.factory import build_data_source

        mt5_source_instance = MagicMock()
        mt5_source_cls = MagicMock(return_value=mt5_source_instance)

        with patch.dict(sys.modules, {
            "backend.data.mt5_historical_source": MagicMock(
                MT5HistoricalDataSource=mt5_source_cls
            )
        }):
            result = build_data_source("mt5", "#Germany40")

        mt5_source_cls.assert_called_once()
        assert result is mt5_source_instance

    def test_dukascopy_source_returns_dukascopy_instance(self):
        from backend.data.factory import build_data_source

        duk_instance = MagicMock()
        duk_cls = MagicMock(return_value=duk_instance)

        # dukascopy_python must be importable
        with patch.dict(sys.modules, {
            "dukascopy_python": MagicMock(fetch=MagicMock()),
            "backend.data.dukascopy_historical_source": MagicMock(
                DukascopyHistoricalDataSource=duk_cls
            ),
        }):
            result = build_data_source("dukascopy", "#Germany40")

        duk_cls.assert_called_once()
        assert result is duk_instance

    def test_dukascopy_eurusd(self):
        from backend.data.factory import build_data_source

        duk_instance = MagicMock()
        duk_cls = MagicMock(return_value=duk_instance)

        with patch.dict(sys.modules, {
            "dukascopy_python": MagicMock(fetch=MagicMock()),
            "backend.data.dukascopy_historical_source": MagicMock(
                DukascopyHistoricalDataSource=duk_cls
            ),
        }):
            result = build_data_source("dukascopy", "EURUSD")

        duk_cls.assert_called_once()
        assert result is duk_instance


# ---------------------------------------------------------------------------
# build_data_source — error cases
# ---------------------------------------------------------------------------

class TestBuildDataSourceErrors:

    def test_unknown_source_raises_value_error(self):
        from backend.data.factory import build_data_source
        with pytest.raises(ValueError, match="Fuente de datos no reconocida"):
            build_data_source("bloomberg", "#Germany40")

    def test_dukascopy_unknown_symbol_raises_value_error(self):
        from backend.data.factory import build_data_source
        with patch.dict(sys.modules, {
            "dukascopy_python": MagicMock(fetch=MagicMock()),
        }):
            with pytest.raises(ValueError, match="no tiene entrada en symbols.json"):
                build_data_source("dukascopy", "XAUUSD_UNKNOWN_XYZ")

    def test_dukascopy_not_installed_raises_value_error(self):
        from backend.data.factory import build_data_source
        # Remove dukascopy_python from sys.modules so the import inside fails
        original = sys.modules.pop("dukascopy_python", None)
        try:
            with patch.dict(sys.modules, {"dukascopy_python": None}):
                with pytest.raises(ValueError, match="dukascopy-python no está instalado"):
                    build_data_source("dukascopy", "#Germany40")
        finally:
            if original is not None:
                sys.modules["dukascopy_python"] = original
