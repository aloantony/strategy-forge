# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Helpers compartidos para ejecutar estrategias en runtime y backtest.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.runtime.timeframes import (
    TIMEFRAME_MAP,
    TIMEFRAME_MINUTES,
    TIMEFRAME_SECONDS,
    lowest_timeframe_label,
    normalize_timeframe_label,
    resolve_timeframe_value,
    timeframe_label,
    timeframe_to_minutes,
    timeframe_to_seconds,
)


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


def _frame_time_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "time" in out.columns:
        out["_runtime_time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
        out = out.dropna(subset=["_runtime_time"]).set_index("_runtime_time")
    else:
        out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
        out = out[~out.index.isna()]
    return out.sort_index()


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    label = normalize_timeframe_label(timeframe)
    if not label:
        raise ValueError(f"Timeframe no soportado para resample: {timeframe!r}")
    if df is None or df.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])

    source = _frame_time_index(df)
    rule = f"{TIMEFRAME_MINUTES[label]}min"
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    for col in ("tick_volume", "volume", "real_volume"):
        if col in source.columns:
            agg[col] = "sum"
    for col in ("spread",):
        if col in source.columns:
            agg[col] = "last"

    out = source.resample(rule, label="left", closed="left").agg(agg)
    out = out.dropna(subset=["open", "high", "low", "close"]).reset_index()
    out = out.rename(columns={"_runtime_time": "time", "index": "time"})
    if "time" not in out.columns:
        out.insert(0, "time", out.index)
    return out.reset_index(drop=True)


def build_timeframe_frames(
    base_df: pd.DataFrame,
    required_timeframes: list[str] | tuple[str, ...] | set[str],
    base_timeframe: str | None = None,
) -> dict[str, pd.DataFrame]:
    labels = []
    for label in required_timeframes or []:
        normalized = normalize_timeframe_label(label)
        if normalized and normalized not in labels:
            labels.append(normalized)
    if not labels:
        labels = ["M1"]

    base_label = normalize_timeframe_label(base_timeframe) or lowest_timeframe_label(labels)
    base_minutes = TIMEFRAME_MINUTES.get(base_label, 1)
    frames: dict[str, pd.DataFrame] = {}
    for label in labels:
        if label == base_label:
            frames[label] = base_df.copy()
            continue
        target_minutes = TIMEFRAME_MINUTES[label]
        if target_minutes < base_minutes:
            raise ValueError(
                f"No se puede construir {label} desde una base {base_label}; "
                "usa una base de menor o igual temporalidad."
            )
        frames[label] = resample_ohlcv(base_df, label)
    return frames


def apply_mtf_strategy_processing(
    frames: dict[str, pd.DataFrame],
    module,
    enable_signals: bool = True,
) -> dict[str, pd.DataFrame]:
    out = {str(k).upper(): v.copy() for k, v in (frames or {}).items()}
    if module is None:
        return out
    if hasattr(module, "prepare_frames"):
        candidate = module.prepare_frames(out)
        if isinstance(candidate, dict):
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
    risk_pct = 0.0
    entry_index = None
    max_entries = None
    block_id = ""
    tier_id = ""

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

        risk_pct_raw = payload.get("risk_pct", 0.0)
        try:
            risk_pct = float(risk_pct_raw) if risk_pct_raw is not None else 0.0
        except (TypeError, ValueError):
            risk_pct = 0.0

        for key, target in (("entry_index", "entry_index"), ("max_entries", "max_entries")):
            raw = payload.get(key)
            if raw is None:
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if target == "entry_index":
                entry_index = value
            else:
                max_entries = value

        block_id = str(payload.get("block_id") or "")
        tier_id = str(payload.get("tier_id") or "")
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
        "risk_pct": risk_pct,
        "entry_index": entry_index,
        "max_entries": max_entries,
        "block_id": block_id,
        "tier_id": tier_id,
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
            "risk_pct": 0.0,
            "entry_index": None,
            "max_entries": None,
            "block_id": "",
            "tier_id": "",
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


def get_strategy_signal_payload_mtf(
    frames: dict[str, pd.DataFrame],
    module,
    verbose: bool = False,
    params=None,
) -> dict:
    if module is None:
        return normalize_signal_payload(None)

    payload = None
    if hasattr(module, "get_last_signal_payload_mtf"):
        try:
            if params is not None:
                payload = module.get_last_signal_payload_mtf(frames, verbose=verbose, params=params)
            else:
                payload = module.get_last_signal_payload_mtf(frames, verbose=verbose)
        except TypeError:
            try:
                payload = module.get_last_signal_payload_mtf(frames, verbose=verbose)
            except TypeError:
                payload = module.get_last_signal_payload_mtf(frames)
    return normalize_signal_payload(payload)


def is_mtf_module(module) -> bool:
    """True si el módulo es multi-timeframe (consume frames, no un df único)."""
    return module is not None and (
        hasattr(module, "get_last_signal_payload_mtf") or hasattr(module, "prepare_frames")
    )


def module_required_timeframes(module, fallback: str = "M1") -> list[str]:
    """Timeframes que necesita el módulo (REQUIRED_TIMEFRAMES + primario), normalizados."""
    out: list[str] = []
    for label in getattr(module, "REQUIRED_TIMEFRAMES", []) or []:
        normalized = normalize_timeframe_label(label)
        if normalized and normalized not in out:
            out.append(normalized)
    primary = normalize_timeframe_label(
        getattr(module, "PRIMARY_TIMEFRAME", None) or get_strategy_timeframe(module) or ""
    )
    if primary and primary not in out:
        out.append(primary)
    if not out:
        out = [normalize_timeframe_label(fallback) or "M1"]
    return out


def analyze_signal(
    module,
    data,
    enable_signals: bool = True,
    verbose: bool = False,
    params=None,
) -> dict:
    """
    Análisis unificado v1/MTF: procesa los datos y devuelve el payload normalizado.

    data: DataFrame (v1, o base para resamplear si el módulo es MTF) o dict
    {timeframe: DataFrame} con los frames ya descargados (preferido en vivo).
    """
    if is_mtf_module(module):
        if isinstance(data, pd.DataFrame):
            frames = build_timeframe_frames(data, module_required_timeframes(module))
        else:
            frames = {normalize_timeframe_label(k) or str(k).upper(): v for k, v in (data or {}).items()}
        prepared = apply_mtf_strategy_processing(frames, module, enable_signals=enable_signals)
        return get_strategy_signal_payload_mtf(prepared, module, verbose=verbose, params=params)

    df = data
    if isinstance(data, dict):
        primary = normalize_timeframe_label(get_strategy_timeframe(module) or "")
        df = data.get(primary) if primary else None
        if df is None and data:
            df = data.get(lowest_timeframe_label(list(data)))
    if df is None:
        return normalize_signal_payload(None)
    processed = apply_strategy_processing(df, module, enable_signals=enable_signals)
    return get_strategy_signal_payload(processed, module, verbose=verbose, params=params)
