"""
Helpers compartidos para ejecutar estrategias en runtime y backtest.
"""

from __future__ import annotations

from typing import Any

try:
    import MetaTrader5 as mt5
    _TF_M1  = mt5.TIMEFRAME_M1   # = 1
    _TF_M5  = mt5.TIMEFRAME_M5   # = 5
    _TF_M15 = mt5.TIMEFRAME_M15  # = 15
    _TF_M30 = mt5.TIMEFRAME_M30  # = 30
    _TF_H1  = mt5.TIMEFRAME_H1   # = 16385
    _TF_H4  = mt5.TIMEFRAME_H4   # = 16388
    _TF_D1  = mt5.TIMEFRAME_D1   # = 16408
except ImportError:
    mt5 = None
    _TF_M1  = 1
    _TF_M5  = 5
    _TF_M15 = 15
    _TF_M30 = 30
    _TF_H1  = 16385
    _TF_H4  = 16388
    _TF_D1  = 16408

import pandas as pd


TIMEFRAME_MAP = {
    "M1": _TF_M1, "M5": _TF_M5, "M15": _TF_M15, "M30": _TF_M30,
    "H1": _TF_H1, "H4": _TF_H4, "D1": _TF_D1,
}


def resolve_timeframe_value(value: Any):
    if value is None:
        return None
    if isinstance(value, str):
        return TIMEFRAME_MAP.get(value.strip().upper())
    if isinstance(value, int) and value in TIMEFRAME_MAP.values():
        return value
    return None


def timeframe_label(timeframe_value: int) -> str:
    reverse_map = {v: k for k, v in TIMEFRAME_MAP.items()}
    return reverse_map.get(timeframe_value, "")


def get_strategy_timeframe(module):
    if module is None:
        return None
    if hasattr(module, "get_timeframe"):
        try:
            return module.get_timeframe()
        except Exception:
            return None
    for key in ("TIMEFRAME", "STRATEGY_TIMEFRAME", "TIMEFRAME_STR"):
        if hasattr(module, key):
            try:
                return getattr(module, key)
            except Exception:
                return None
    return None


def apply_strategy_processing(
    df: pd.DataFrame,
    module,
    enable_signals: bool = True,
) -> pd.DataFrame:
    out = df.copy()
    if module is None:
        return out

    if hasattr(module, "prepare_dataframe"):
        candidate = module.prepare_dataframe(out)
        if isinstance(candidate, pd.DataFrame):
            out = candidate

    if hasattr(module, "compute_dir1_and_signals"):
        candidate = module.compute_dir1_and_signals(out, enable_signals)
        if isinstance(candidate, pd.DataFrame):
            out = candidate
    elif hasattr(module, "compute_signals"):
        candidate = module.compute_signals(out, enable_signals)
        if isinstance(candidate, pd.DataFrame):
            out = candidate

    return out


def normalize_signal(signal) -> str:
    value = str(signal or "").strip().lower()
    return value if value in {"buy", "sell", "none"} else "none"


def normalize_signal_payload(payload) -> dict:
    signal_raw = payload
    reason_raw = ""
    pyramiding = False
    atr_value = 0.0
    dynamic_sizing = False
    volume_ratio = 0.0
    sl_atr_mult = 1.0
    tp_atr_mult = 2.0
    pyramid_atr_mult = 0.5

    if isinstance(payload, dict):
        signal_raw = (
            payload.get("signal")
            or payload.get("side")
            or payload.get("action")
            or payload.get("decision")
            or "none"
        )
        reason_raw = (
            payload.get("reason")
            or payload.get("motivo")
            or payload.get("message")
            or payload.get("detail")
            or payload.get("why")
            or ""
        )
        pyramiding_raw = payload.get("pyramiding", False)
        pyramiding = bool(pyramiding_raw) if pyramiding_raw is not None else False

        atr_raw = payload.get("atr_value", 0.0)
        try:
            atr_value = float(atr_raw) if atr_raw is not None else 0.0
        except (TypeError, ValueError):
            atr_value = 0.0

        dynamic_sizing_raw = payload.get("dynamic_sizing", False)
        dynamic_sizing = bool(dynamic_sizing_raw) if dynamic_sizing_raw is not None else False

        volume_ratio_raw = payload.get("volume_ratio", 0.0)
        try:
            volume_ratio = float(volume_ratio_raw) if volume_ratio_raw is not None else 0.0
        except (TypeError, ValueError):
            volume_ratio = 0.0

        sl_atr_mult_raw = payload.get("sl_atr_mult", 1.0)
        try:
            sl_atr_mult = float(sl_atr_mult_raw) if sl_atr_mult_raw is not None else 1.0
        except (TypeError, ValueError):
            sl_atr_mult = 1.0

        tp_atr_mult_raw = payload.get("tp_atr_mult", 2.0)
        try:
            tp_atr_mult = float(tp_atr_mult_raw) if tp_atr_mult_raw is not None else 2.0
        except (TypeError, ValueError):
            tp_atr_mult = 2.0

        pyramid_atr_mult_raw = payload.get("pyramid_atr_mult", 0.5)
        try:
            pyramid_atr_mult = float(pyramid_atr_mult_raw) if pyramid_atr_mult_raw is not None else 0.5
        except (TypeError, ValueError):
            pyramid_atr_mult = 0.5
    elif isinstance(payload, (tuple, list)):
        if len(payload) > 0:
            signal_raw = payload[0]
        if len(payload) > 1:
            reason_raw = payload[1]

    reason = str(reason_raw or "").strip()
    if len(reason) > 160:
        reason = reason[:157].rstrip() + "..."

    return {
        "signal": normalize_signal(signal_raw),
        "reason": reason,
        "pyramiding": pyramiding,
        "atr_value": atr_value,
        "dynamic_sizing": dynamic_sizing,
        "volume_ratio": volume_ratio,
        "sl_atr_mult": sl_atr_mult,
        "tp_atr_mult": tp_atr_mult,
        "pyramid_atr_mult": pyramid_atr_mult,
    }


def get_strategy_signal_payload(
    df: pd.DataFrame,
    module,
    verbose: bool = False,
    params=None,
) -> dict:
    if module is None:
        return {
            "signal": "none",
            "reason": "",
            "pyramiding": False,
            "atr_value": 0.0,
            "dynamic_sizing": False,
            "volume_ratio": 0.0,
        }

    payload = None
    if hasattr(module, "get_last_signal_payload"):
        try:
            if params is not None:
                payload = module.get_last_signal_payload(df, verbose=verbose, params=params)
            else:
                payload = module.get_last_signal_payload(df, verbose=verbose)
        except TypeError:
            try:
                payload = module.get_last_signal_payload(df, verbose=verbose)
            except TypeError:
                payload = module.get_last_signal_payload(df)

    if payload is None and hasattr(module, "get_last_signal"):
        try:
            if params is not None:
                payload = module.get_last_signal(df, verbose=verbose, params=params)
            else:
                payload = module.get_last_signal(df, verbose=verbose)
        except TypeError:
            try:
                payload = module.get_last_signal(df, verbose=verbose)
            except TypeError:
                payload = module.get_last_signal(df)

    return normalize_signal_payload(payload)
