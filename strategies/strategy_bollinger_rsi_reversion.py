"""
Scalping M1:
Reversión rápida con Bollinger + RSI corto + filtro de actividad.
"""

from datetime import datetime
import pandas as pd


TIMEFRAME = "M1"

BB_LENGTH = 20
BB_STD = 1.8
RSI_LENGTH = 7
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
VOL_LOOKBACK = 30
MIN_BB_WIDTH_PCT = 0.00006
MIN_VOLUME_RATIO = 0.75


DATA_WINDOW_FIELDS = [
    {"key": "bb_basis", "label": "BB Basis", "format": "price", "section": "Bollinger"},
    {"key": "bb_upper", "label": "BB Upper", "format": "price", "section": "Bollinger"},
    {"key": "bb_lower", "label": "BB Lower", "format": "price", "section": "Bollinger"},
    {"key": "bb_width_pct", "label": "BB Width %", "format": "percent", "section": "Bollinger"},
    {"key": "rsi_7", "label": "RSI 7", "format": "number", "section": "Momentum"},
    {"key": "volume_ratio", "label": "Volume Ratio", "format": "number", "section": "Volume"},
    {"key": "long_setup", "label": "Long Setup", "format": "int", "section": "Signals", "shift": 1},
    {"key": "short_setup", "label": "Short Setup", "format": "int", "section": "Signals", "shift": 1},
    {"key": "up_sig", "label": "Buy Signal", "format": "int", "section": "Signals", "shift": 1},
    {"key": "dn_sig", "label": "Sell Signal", "format": "int", "section": "Signals", "shift": 1},
]


def log_strategy(message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [SCALP_BOLL_RSI] {message}")


def _numeric(df: pd.DataFrame, key: str) -> pd.Series:
    return pd.to_numeric(df.get(key), errors="coerce")


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    required = {"open", "close"}
    if not required.issubset(out.columns):
        return out

    close = _numeric(out, "close")
    bb_basis = close.rolling(BB_LENGTH, min_periods=BB_LENGTH).mean()
    bb_std = close.rolling(BB_LENGTH, min_periods=BB_LENGTH).std(ddof=0)
    bb_upper = bb_basis + (bb_std * BB_STD)
    bb_lower = bb_basis - (bb_std * BB_STD)
    bb_width_pct = (bb_upper - bb_lower) / bb_basis.replace(0.0, float("nan"))
    rsi_7 = _rsi(close, RSI_LENGTH)

    if "tick_volume" in out.columns:
        volume = _numeric(out, "tick_volume")
    elif "volume" in out.columns:
        volume = _numeric(out, "volume")
    else:
        volume = pd.Series(1.0, index=out.index, dtype="float64")
    vol_ma = volume.rolling(VOL_LOOKBACK, min_periods=5).mean()
    volume_ratio = volume / vol_ma.replace(0.0, float("nan"))

    out["bb_basis"] = bb_basis
    out["bb_upper"] = bb_upper
    out["bb_lower"] = bb_lower
    out["bb_width_pct"] = bb_width_pct
    out["rsi_7"] = rsi_7
    out["volume_ratio"] = volume_ratio
    return out


def compute_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:
    out = df.copy()
    needed = {"open", "close", "bb_upper", "bb_lower", "bb_width_pct", "rsi_7", "volume_ratio"}
    if not needed.issubset(out.columns):
        out["long_setup"] = 0
        out["short_setup"] = 0
        out["up_sig"] = 0
        out["dn_sig"] = 0
        return out

    open_price = _numeric(out, "open")
    close = _numeric(out, "close")
    bb_upper = _numeric(out, "bb_upper")
    bb_lower = _numeric(out, "bb_lower")
    bb_width_pct = _numeric(out, "bb_width_pct")
    rsi_7 = _numeric(out, "rsi_7")
    volume_ratio = _numeric(out, "volume_ratio")

    width_ok = bb_width_pct >= MIN_BB_WIDTH_PCT
    volume_ok = volume_ratio >= MIN_VOLUME_RATIO
    bullish_candle = close > open_price
    bearish_candle = close < open_price

    reentry_from_below = (close.shift(1) < bb_lower.shift(1)) & (close >= bb_lower)
    reentry_from_above = (close.shift(1) > bb_upper.shift(1)) & (close <= bb_upper)

    rsi_recover_up = (rsi_7.shift(1) <= RSI_OVERSOLD) & (rsi_7 > rsi_7.shift(1))
    rsi_recover_down = (rsi_7.shift(1) >= RSI_OVERBOUGHT) & (rsi_7 < rsi_7.shift(1))

    long_setup = width_ok & volume_ok & reentry_from_below & rsi_recover_up & bullish_candle
    short_setup = width_ok & volume_ok & reentry_from_above & rsi_recover_down & bearish_candle

    if enable_signals:
        buy_signal = long_setup
        sell_signal = short_setup
    else:
        buy_signal = pd.Series(False, index=out.index)
        sell_signal = pd.Series(False, index=out.index)

    out["long_setup"] = long_setup.astype(int)
    out["short_setup"] = short_setup.astype(int)
    out["up_sig"] = buy_signal.astype(int)
    out["dn_sig"] = sell_signal.astype(int)
    return out


def get_last_signal_payload(df: pd.DataFrame, verbose: bool = False) -> dict:
    if df is None or len(df) < 3:
        return {"signal": "none", "reason": "Sin datos suficientes"}

    row = df.iloc[len(df) - 2]
    buy = bool(int(row.get("up_sig", 0) or 0))
    sell = bool(int(row.get("dn_sig", 0) or 0))

    if buy and not sell:
        if verbose:
            log_strategy("BUY: reversion rapida en banda inferior")
        return {"signal": "buy", "reason": "Scalp reversión: reingreso BB inferior + RSI7"}
    if sell and not buy:
        if verbose:
            log_strategy("SELL: reversion rapida en banda superior")
        return {"signal": "sell", "reason": "Scalp reversión: reingreso BB superior + RSI7"}
    return {"signal": "none", "reason": "Sin trigger de reversion M1"}


def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    payload = get_last_signal_payload(df, verbose=verbose)
    return payload.get("signal", "none")
