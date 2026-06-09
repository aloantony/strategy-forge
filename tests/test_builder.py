"""
tests/test_builder.py — Acceptance tests for strategy_builder/generator.py (TASK-017).

Run with: python tests/test_builder.py
"""
import ast
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import strategy_runtime
from strategy_builder.generator import (
    GeneratorError,
    NameCollisionError,
    ValidationError,
    build_strategy_module,
    emit_condition,
    generate_magic_number,
    generate_strategy_file,
    handle_save_edit,
    handle_save_new,
    sanitize_name,
    validate_strategy_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EMA_RSI_CONFIG = {
    "schema_version": 1,
    "name": "ema_rsi_cross",
    "display_name": "EMA Cross + RSI Filter",
    "description": "Buy when fast EMA crosses above slow EMA and RSI is in momentum zone.",
    "timeframe": "H1",
    "magic_number": 47231,
    "indicators": [
        {"id": "EMA", "params": {"period": 9},  "columns": ["ema_9"],  "pre_computed": False},
        {"id": "EMA", "params": {"period": 21}, "columns": ["ema_21"], "pre_computed": False},
        {"id": "RSI", "params": {"period": 14}, "columns": ["rsi_14"], "pre_computed": False},
    ],
    "buy_condition": {
        "type": "AND",
        "children": [
            {"type": "condition", "left": "ema_9",  "op": ">", "right": "ema_21"},
            {"type": "condition", "left": "rsi_14", "op": ">", "right": 50},
        ],
    },
    "sell_condition": {
        "type": "AND",
        "children": [
            {"type": "condition", "left": "ema_9",  "op": "<", "right": "ema_21"},
            {"type": "condition", "left": "rsi_14", "op": "<", "right": 50},
        ],
    },
}

COMPLEX_OR_CONFIG = {
    "schema_version": 1,
    "name": "complex_or",
    "display_name": "Complex OR Strategy",
    "description": "",
    "timeframe": "M15",
    "magic_number": 55555,
    "indicators": [
        {"id": "RSI", "params": {"period": 14}, "columns": ["rsi_14"], "pre_computed": False},
        {"id": "EMA", "params": {"period": 9},  "columns": ["ema_9"],  "pre_computed": False},
        {
            "id": "BB",
            "params": {"period": 20, "multiplier": 2.0},
            "columns": ["bb_basis_20", "bb_upper_20", "bb_lower_20", "bb_width_pct_20"],
            "pre_computed": False,
        },
        {
            "id": "VOLUME_RATIO",
            "params": {"lookback": 30},
            "columns": ["volume_ratio_30"],
            "pre_computed": False,
        },
    ],
    "buy_condition": {
        "type": "OR",
        "children": [
            {
                "type": "AND",
                "children": [
                    {"type": "condition", "left": "rsi_14", "op": "<", "right": 30},
                    {"type": "condition", "left": "close",  "op": ">", "right": "ema_9"},
                ],
            },
            {
                "type": "AND",
                "children": [
                    {"type": "condition", "left": "close",           "op": ">", "right": "bb_upper_20"},
                    {"type": "condition", "left": "volume_ratio_30", "op": ">", "right": 1.5},
                ],
            },
        ],
    },
    "sell_condition": {
        "type": "condition",
        "left": "rsi_14",
        "op": ">",
        "right": 70,
    },
}


def make_df(n=100):
    np.random.seed(42)
    close = pd.Series(np.cumsum(np.random.randn(n)) + 100)
    return pd.DataFrame({
        "close":       close,
        "high":        close + 0.5,
        "low":         close - 0.5,
        "open":        close,
        "tick_volume": np.random.randint(1, 100, n).astype(float),
    })


def load_module(py_path: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("_test_strategy", py_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_canonical_example():
    """Generated file matches spec §8 structure and passes ast.parse."""
    config = json.loads(json.dumps(EMA_RSI_CONFIG))
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        validate_strategy_config(config, is_new=True, strategies_dir=d)
        py_path = generate_strategy_file(config, strategies_dir=d)

        content = py_path.read_text()
        ast.parse(content)

        # Isolation rule
        for forbidden in ("import config", "import trading", "import gui_charts"):
            assert forbidden not in content, f"Isolation violated: {forbidden}"

        # Required symbols
        for sym in ("TIMEFRAME", "MAGIC_NUMBER", "DATA_WINDOW_FIELDS",
                    "prepare_dataframe", "compute_signals",
                    "get_last_signal_payload", "get_last_signal"):
            assert sym in content, f"Missing symbol: {sym}"

        # Companion .json
        json_path = d / "strategy_ema_rsi_cross.json"
        assert json_path.exists()
        stored = json.loads(json_path.read_text())
        assert stored["magic_number"] == 47231

    print("PASS test_canonical_example")


def test_round_trip():
    """Loading stored .json and regenerating produces identical .py."""
    config = json.loads(json.dumps(EMA_RSI_CONFIG))
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        py_path = generate_strategy_file(config, strategies_dir=d)
        original = py_path.read_text()

        stored = json.loads((d / "strategy_ema_rsi_cross.json").read_text())
        py_path2 = generate_strategy_file(stored, strategies_dir=d)
        assert py_path2.read_text() == original

    print("PASS test_round_trip")


def test_get_last_signal_produces_valid_values():
    """Generated strategy returns only 'buy', 'sell', or 'none' on real data."""
    config = json.loads(json.dumps(EMA_RSI_CONFIG))
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        py_path = generate_strategy_file(config, strategies_dir=d)
        mod = load_module(py_path)

        df = make_df()
        df2 = mod.prepare_dataframe(df)
        sig = mod.get_last_signal(df2)
        assert sig in ("buy", "sell", "none"), f"Unexpected signal: {sig!r}"

    print(f"PASS test_get_last_signal_produces_valid_values (signal={sig!r})")


def test_complex_or_nested_condition():
    """OR-nested condition tree generates valid Python and valid signals."""
    config = json.loads(json.dumps(COMPLEX_OR_CONFIG))
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        validate_strategy_config(config, is_new=True, strategies_dir=d)
        py_path = generate_strategy_file(config, strategies_dir=d)
        ast.parse(py_path.read_text())

        mod = load_module(py_path)
        df = make_df()
        df2 = mod.prepare_dataframe(df)
        sig = mod.get_last_signal(df2)
        assert sig in ("buy", "sell", "none")

    print(f"PASS test_complex_or_nested_condition (signal={sig!r})")


def test_edit_flow_rename():
    """Edit flow: rename writes new files, deletes old ones, preserves magic_number."""
    config = json.loads(json.dumps(COMPLEX_OR_CONFIG))
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        generate_strategy_file(config, strategies_dir=d)
        # Write companion json (handle_save_edit reads it)
        (d / "strategy_complex_or.json").write_text(json.dumps(config))

        edited = json.loads(json.dumps(config))
        edited["display_name"] = "Renamed Strategy"
        py2 = handle_save_edit(edited, "complex_or", strategies_dir=d)

        assert (d / "strategy_renamed_strategy.py").exists()
        assert (d / "strategy_renamed_strategy.json").exists()
        assert not (d / "strategy_complex_or.py").exists()
        assert not (d / "strategy_complex_or.json").exists()

        stored2 = json.loads((d / "strategy_renamed_strategy.json").read_text())
        assert stored2["magic_number"] == 55555  # preserved

    print("PASS test_edit_flow_rename")


def test_no_prepare_dataframe_when_all_precomputed():
    """prepare_dataframe is NOT emitted when all indicators are pre_computed."""
    config = {
        "schema_version": 1,
        "name": "pre_only",
        "display_name": "Pre Only",
        "description": "",
        "timeframe": "M1",
        "magic_number": 99999,
        "indicators": [
            {
                "id": "SUPERTREND",
                "params": {},
                "columns": ["supertrend", "supertrend_dir", "supertrend_up", "supertrend_down"],
                "pre_computed": True,
            }
        ],
        "buy_condition": {
            "type": "condition", "left": "supertrend_dir", "op": "==", "right": 1
        },
        "sell_condition": {
            "type": "condition", "left": "supertrend_dir", "op": "==", "right": -1
        },
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        validate_strategy_config(config, is_new=True, strategies_dir=d)
        py_path = generate_strategy_file(config, strategies_dir=d)
        content = py_path.read_text()
        assert "def prepare_dataframe" not in content
        ast.parse(content)

    print("PASS test_no_prepare_dataframe_when_all_precomputed")


def test_atr_donchian():
    """ATR + DONCHIAN indicators generate correct computation blocks."""
    config = {
        "schema_version": 1,
        "name": "atr_donchian",
        "display_name": "ATR Donchian",
        "description": "",
        "timeframe": "H1",
        "magic_number": 12345,
        "indicators": [
            {
                "id": "ATR",
                "params": {"period": 14},
                "columns": ["atr_14", "atr_pct_14"],
                "pre_computed": False,
            },
            {
                "id": "DONCHIAN",
                "params": {"period": 20},
                "columns": ["donchian_high_20", "donchian_low_20", "donchian_mid_20"],
                "pre_computed": False,
            },
        ],
        "buy_condition": {
            "type": "condition", "left": "close", "op": ">", "right": "donchian_high_20"
        },
        "sell_condition": {
            "type": "condition", "left": "close", "op": "<", "right": "donchian_low_20"
        },
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        validate_strategy_config(config, is_new=True, strategies_dir=d)
        py_path = generate_strategy_file(config, strategies_dir=d)
        content = py_path.read_text()
        ast.parse(content)
        assert "_atr(" in content
        assert "donchian_high_20" in content

        mod = load_module(py_path)
        df = make_df()
        df2 = mod.prepare_dataframe(df)
        sig = mod.get_last_signal(df2)
        assert sig in ("buy", "sell", "none")

    print("PASS test_atr_donchian")


def test_validation_errors():
    """Validator rejects bad name, unknown column, bad operator."""
    # Bad name
    config = json.loads(json.dumps(EMA_RSI_CONFIG))
    config["name"] = "123bad"
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        try:
            validate_strategy_config(config, is_new=True, strategies_dir=d)
            assert False, "Should have raised"
        except ValidationError as e:
            assert "name" in str(e).lower()
    print("PASS test_validation_bad_name")

    # Unknown column in condition
    config2 = json.loads(json.dumps(EMA_RSI_CONFIG))
    config2["buy_condition"] = {
        "type": "condition", "left": "nonexistent_col", "op": "<", "right": 30
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        try:
            validate_strategy_config(config2, is_new=True, strategies_dir=d)
            assert False, "Should have raised"
        except ValidationError as e:
            assert "nonexistent_col" in str(e)
    print("PASS test_validation_unknown_column")

    # Bad operator
    config3 = json.loads(json.dumps(EMA_RSI_CONFIG))
    config3["buy_condition"] = {
        "type": "AND",
        "children": [
            {"type": "condition", "left": "rsi_14", "op": "INJECT", "right": 30},
            {"type": "condition", "left": "ema_9",  "op": ">", "right": "ema_21"},
        ],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        try:
            validate_strategy_config(config3, is_new=True, strategies_dir=d)
            assert False, "Should have raised"
        except ValidationError as e:
            assert "INJECT" in str(e)
    print("PASS test_validation_bad_operator")


def test_emit_condition_spec_examples():
    """emit_condition output matches TASK-014b spec examples exactly."""
    # Two-level nesting example from spec
    tree = {
        "type": "OR",
        "children": [
            {
                "type": "AND",
                "children": [
                    {"type": "condition", "left": "rsi_14", "op": "<", "right": 30},
                    {"type": "condition", "left": "close",  "op": ">", "right": "ema_9"},
                ],
            },
            {
                "type": "AND",
                "children": [
                    {"type": "condition", "left": "close",           "op": ">", "right": "bb_upper_20"},
                    {"type": "condition", "left": "volume_ratio_30", "op": ">", "right": 1.5},
                ],
            },
        ],
    }
    expected = (
        '((df.iloc[-2]["rsi_14"] < 30 and df.iloc[-2]["close"] > df.iloc[-2]["ema_9"]) '
        'or (df.iloc[-2]["close"] > df.iloc[-2]["bb_upper_20"] and df.iloc[-2]["volume_ratio_30"] > 1.5))'
    )
    result = emit_condition(tree)
    assert result == expected, f"\nExpected: {expected}\nGot:      {result}"
    print("PASS test_emit_condition_spec_examples")


def test_name_collision():
    """validate_strategy_config raises ValidationError when name already taken."""
    config = json.loads(json.dumps(EMA_RSI_CONFIG))
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        # First create succeeds
        generate_strategy_file(config, strategies_dir=d)
        # Write companion json so it's detected as Builder strategy
        (d / "strategy_ema_rsi_cross.json").write_text(json.dumps(config))

        # Trying to create again with same name should fail validation
        config2 = json.loads(json.dumps(EMA_RSI_CONFIG))
        try:
            validate_strategy_config(config2, is_new=True, strategies_dir=d)
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    print("PASS test_name_collision")


def test_preview_module_exposes_overlay_metadata():
    """Preview modules expose object-tree metadata and chart aliases for live Builder preview."""
    config = {
        "schema_version": 1,
        "name": "preview_overlay",
        "display_name": "Preview Overlay",
        "description": "",
        "timeframe": "M15",
        "magic_number": 12345,
        "indicators": [
            {
                "id": "BB",
                "params": {"period": 20, "multiplier": 2.0},
                "columns": ["bb_basis_20", "bb_upper_20", "bb_lower_20", "bb_width_pct_20"],
                "pre_computed": False,
            },
            {
                "id": "TCI",
                "params": {},
                "columns": ["tci", "tci_signal", "tci_hist"],
                "pre_computed": True,
            },
        ],
        "buy_condition": {
            "type": "AND",
            "children": [
                {"type": "condition", "left": "close", "op": ">", "right": "bb_basis_20"},
                {"type": "condition", "left": "bb_width_pct_20", "op": ">", "right": 0.01},
            ],
        },
        "sell_condition": {
            "type": "AND",
            "children": [
                {"type": "condition", "left": "close", "op": "<", "right": "bb_basis_20"},
                {"type": "condition", "left": "bb_width_pct_20", "op": ">", "right": 0.01},
            ],
        },
    }

    mod = build_strategy_module(config)
    assert hasattr(mod, "OBJECT_TREE_ITEMS")
    assert any(item.get("key") == "atr_bands" for item in mod.OBJECT_TREE_ITEMS)
    assert any(item.get("key") == "tci" for item in mod.OBJECT_TREE_ITEMS)

    df = make_df()
    df["tci"] = 0.0
    df["tci_signal"] = 0.0
    df["tci_hist"] = 0.0
    df2 = mod.prepare_dataframe(df)
    assert "average" in df2.columns
    assert "upper" in df2.columns
    assert "lower" in df2.columns
    assert df2["average"].equals(df2["bb_basis_20"])
    assert df2["upper"].equals(df2["bb_upper_20"])
    assert df2["lower"].equals(df2["bb_lower_20"])

    print("PASS test_preview_module_exposes_overlay_metadata")


def test_magic_number_unique():
    """handle_save_new assigns a magic not already used by another Builder strategy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        c1 = json.loads(json.dumps(EMA_RSI_CONFIG)); c1["display_name"] = "Strat One"
        c2 = json.loads(json.dumps(EMA_RSI_CONFIG)); c2["display_name"] = "Strat Two"
        handle_save_new(c1, strategies_dir=d)
        handle_save_new(c2, strategies_dir=d)

        m1 = json.loads((d / "strategy_strat_one.json").read_text())["magic_number"]
        m2 = json.loads((d / "strategy_strat_two.json").read_text())["magic_number"]
        assert m1 != m2, "Two strategies must not share a magic number"

        # generate_magic_number must never return an already-used value
        used = {m1, m2}
        for _ in range(50):
            assert generate_magic_number(d) not in used

    print("PASS test_magic_number_unique")


def test_validation_payload_extra_fields():
    """Validator rejects payload_extra_fields with unknown columns; accepts valid ones."""
    # Invalid: column reference that does not exist
    bad = json.loads(json.dumps(EMA_RSI_CONFIG))
    bad["payload_extra_fields"] = [
        {"key": "foo", "type": "column", "value": "does_not_exist"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        try:
            validate_strategy_config(bad, is_new=True, strategies_dir=d)
            assert False, "Should have raised"
        except ValidationError as e:
            assert "does_not_exist" in str(e)
    print("PASS test_validation_payload_extra_fields_invalid")

    # Valid: literal + existing column, both emitted into get_last_signal_payload
    good = json.loads(json.dumps(EMA_RSI_CONFIG))
    good["payload_extra_fields"] = [
        {"key": "flag", "type": "literal", "value": True},
        {"key": "rsi_value", "type": "column", "value": "rsi_14"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        validate_strategy_config(good, is_new=True, strategies_dir=d)
        py_path = generate_strategy_file(good, strategies_dir=d)
        content = py_path.read_text()
        ast.parse(content)
        assert '"flag"' in content
        assert '"rsi_value"' in content
        assert 'df.iloc[-2]["rsi_14"]' in content
    print("PASS test_validation_payload_extra_fields_valid")


def test_vortex_indicator_generation():
    """VORTEX is available in Builder v1 and exposes direction/cross columns."""
    config = {
        "schema_version": 1,
        "name": "vortex_simple",
        "display_name": "Vortex Simple",
        "description": "",
        "timeframe": "M2",
        "magic_number": 23456,
        "indicators": [
            {
                "id": "VORTEX",
                "params": {"period": 14},
                "columns": [
                    "vi_plus_14",
                    "vi_minus_14",
                    "vortex_dir_14",
                    "vortex_cross_up_14",
                    "vortex_cross_down_14",
                ],
                "pre_computed": False,
            }
        ],
        "buy_condition": {"type": "condition", "left": "vortex_cross_up_14", "op": ">", "right": 0},
        "sell_condition": {"type": "condition", "left": "vortex_cross_down_14", "op": ">", "right": 0},
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        validate_strategy_config(config, is_new=True, strategies_dir=d)
        py_path = generate_strategy_file(config, strategies_dir=d, is_new=True)
        mod = load_module(py_path)
        df2 = mod.prepare_dataframe(make_df(80))
        for col in ("vi_plus_14", "vi_minus_14", "vortex_dir_14", "vortex_cross_up_14", "vortex_cross_down_14"):
            assert col in df2.columns
        assert mod.TIMEFRAME == "M2"
    print("PASS test_vortex_indicator_generation")


def test_mtf_schema_v2_generation_and_payload():
    """Builder v2 can generate an MTF strategy module without affecting v1."""
    idx = pd.date_range("2026-01-01 09:00", periods=120, freq="1min", tz="UTC")
    close = pd.Series(np.linspace(100, 110, len(idx)))
    df = pd.DataFrame({
        "time": idx,
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "tick_volume": np.ones(len(idx)) * 100,
    })
    config = {
        "schema_version": 2,
        "mode": "multi_timeframe",
        "name": "mtf_vortex",
        "display_name": "MTF Vortex",
        "description": "",
        "primary_timeframe": "M1",
        "magic_number": 34567,
        "frames": [{"id": "M1", "timeframe": "M1"}, {"id": "M2", "timeframe": "M2"}],
        "indicators": [],
        "blocks": [
            {
                "id": "A_scalp",
                "trigger_timeframe": "M1",
                "confirm_timeframes": ["M2"],
                "risk_tiers": [0.005, 0.0025],
                "atr_sl_mult": 1.5,
                "tp_ratio": 2.0,
            }
        ],
    }

    mod = build_strategy_module(config, module_name="mtf_builder_preview")
    assert mod.SCHEMA_VERSION == 2
    assert mod.REQUIRED_TIMEFRAMES == ["M1", "M2"]
    frames = strategy_runtime.build_timeframe_frames(df, mod.REQUIRED_TIMEFRAMES, base_timeframe="M1")
    prepared = mod.prepare_frames(frames)
    assert "atr_14" in prepared["M1"].columns
    assert "vortex_dir_14" in prepared["M2"].columns
    payload = strategy_runtime.get_strategy_signal_payload_mtf(prepared, mod)
    assert payload["signal"] in ("buy", "sell", "none")
    assert "risk_pct" in payload
    print("PASS test_mtf_schema_v2_generation_and_payload")


if __name__ == "__main__":
    test_canonical_example()
    test_round_trip()
    test_get_last_signal_produces_valid_values()
    test_complex_or_nested_condition()
    test_edit_flow_rename()
    test_no_prepare_dataframe_when_all_precomputed()
    test_atr_donchian()
    test_validation_errors()
    test_emit_condition_spec_examples()
    test_name_collision()
    test_preview_module_exposes_overlay_metadata()
    test_magic_number_unique()
    test_validation_payload_extra_fields()
    test_vortex_indicator_generation()
    test_mtf_schema_v2_generation_and_payload()
    print("\nAll tests passed.")
