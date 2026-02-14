"""
Scalping M1:
EMA 9/21 + VWAP intradía + RSI para continuidad en micro-tendencia.
"""

from datetime import datetime
import pandas as pd


TIMEFRAME = "M1"

EMA_FAST = 9
EMA_SLOW = 21
RSI_LENGTH = 14
ATR_LENGTH = 14
VOL_LOOKBACK = 30

RSI_BUY_MIN = 50.0
RSI_BUY_MAX = 78.0
RSI_SELL_MIN = 22.0
RSI_SELL_MAX = 50.0
MIN_ATR_PCT = 0.00005
MIN_VOLUME_RATIO = 0.80
PULLBACK_ATR_FACTOR = 0.35

_test_flip = False


DATA_WINDOW_FIELDS = [
    {"key": "ema_fast", "label": "EMA Fast (9)", "format": "price", "section": "Trend"},
    {"key": "ema_slow", "label": "EMA Slow (21)", "format": "price", "section": "Trend"},
    {"key": "vwap", "label": "VWAP", "format": "price", "section": "Trend"},
    {"key": "rsi_14", "label": "RSI 14", "format": "number", "section": "Momentum"},
    {"key": "atr_14", "label": "ATR 14", "format": "price", "section": "Volatility"},
    {"key": "atr_pct", "label": "ATR %", "format": "percent", "section": "Volatility"},
    {"key": "volume_ratio", "label": "Volume Ratio", "format": "number", "section": "Volume"},
    {"key": "long_setup", "label": "Long Setup", "format": "int", "section": "Signals", "shift": 1},
    {"key": "short_setup", "label": "Short Setup", "format": "int", "section": "Signals", "shift": 1},
    {"key": "up_sig", "label": "Buy Signal", "format": "int", "section": "Signals", "shift": 1},
    {"key": "dn_sig", "label": "Sell Signal", "format": "int", "section": "Signals", "shift": 1},
]


def log_strategy(message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [SCALP_EMA_VWAP] {message}")


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


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()


def _intraday_vwap(df: pd.DataFrame, high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price = (high + low + close) / 3.0
    weighted_price = typical_price * volume

    if "time" in df.columns:
        session_key = pd.to_datetime(df["time"], utc=True, errors="coerce").dt.floor("D")
    else:
        session_key = pd.Series(0, index=df.index)

    cum_wp = weighted_price.groupby(session_key).cumsum()
    cum_vol = volume.groupby(session_key).cumsum().replace(0.0, float("nan"))
    return cum_wp / cum_vol


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    required = {"high", "low", "close"}
    if not required.issubset(out.columns):
        return out

    close = _numeric(out, "close")
    high = _numeric(out, "high")
    low = _numeric(out, "low")

    if "tick_volume" in out.columns:
        volume = _numeric(out, "tick_volume")
    elif "volume" in out.columns:
        volume = _numeric(out, "volume")
    else:
        volume = pd.Series(1.0, index=out.index, dtype="float64")

    ema_fast = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()
    vwap = _intraday_vwap(out, high, low, close, volume)
    rsi_14 = _rsi(close, RSI_LENGTH)
    atr_14 = _atr(high, low, close, ATR_LENGTH)
    atr_pct = atr_14 / close.replace(0.0, float("nan"))
    vol_ma = volume.rolling(VOL_LOOKBACK, min_periods=5).mean()
    volume_ratio = volume / vol_ma.replace(0.0, float("nan"))

    out["ema_fast"] = ema_fast
    out["ema_slow"] = ema_slow
    out["vwap"] = vwap
    out["rsi_14"] = rsi_14
    out["atr_14"] = atr_14
    out["atr_pct"] = atr_pct
    out["volume_ratio"] = volume_ratio
    return out


def compute_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:
    out = df.copy()
    needed = {
        "close",
        "ema_fast",
        "ema_slow",
        "vwap",
        "rsi_14",
        "atr_14",
        "atr_pct",
        "volume_ratio",
    }
    if not needed.issubset(out.columns):
        out["long_setup"] = 0
        out["short_setup"] = 0
        out["up_sig"] = 0
        out["dn_sig"] = 0
        return out

    close = _numeric(out, "close")
    ema_fast = _numeric(out, "ema_fast")
    ema_slow = _numeric(out, "ema_slow")
    vwap = _numeric(out, "vwap")
    rsi_14 = _numeric(out, "rsi_14")
    atr_14 = _numeric(out, "atr_14")
    atr_pct = _numeric(out, "atr_pct")
    volume_ratio = _numeric(out, "volume_ratio")

    trend_up = (ema_fast > ema_slow) & (close >= vwap)
    trend_down = (ema_fast < ema_slow) & (close <= vwap)
    enough_volatility = atr_pct >= MIN_ATR_PCT
    volume_ok = volume_ratio >= MIN_VOLUME_RATIO

    rsi_buy_zone = (rsi_14 >= RSI_BUY_MIN) & (rsi_14 <= RSI_BUY_MAX)
    rsi_sell_zone = (rsi_14 >= RSI_SELL_MIN) & (rsi_14 <= RSI_SELL_MAX)

    pullback_long_prev = close.shift(1) <= (ema_fast.shift(1) + atr_14.shift(1) * PULLBACK_ATR_FACTOR)
    pullback_short_prev = close.shift(1) >= (ema_fast.shift(1) - atr_14.shift(1) * PULLBACK_ATR_FACTOR)
    reclaim_long = close > ema_fast
    reclaim_short = close < ema_fast

    long_setup = trend_up & enough_volatility & volume_ok & rsi_buy_zone
    short_setup = trend_down & enough_volatility & volume_ok & rsi_sell_zone

    if enable_signals:
        buy_signal = long_setup & pullback_long_prev & reclaim_long
        sell_signal = short_setup & pullback_short_prev & reclaim_short
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
            log_strategy("BUY: impulso M1 con EMA/VWAP")
        return {"signal": "buy", "reason": "Scalp tendencia: recaptura EMA9 sobre VWAP"}
    if sell and not buy:
        if verbose:
            log_strategy("SELL: impulso M1 con EMA/VWAP")
        return {"signal": "sell", "reason": "Scalp tendencia: rechazo EMA9 bajo VWAP"}
    return {"signal": "none", "reason": "Sin trigger de tendencia M1"}


def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    payload = get_last_signal_payload(df, verbose=verbose)
    return payload.get("signal", "none")


def get_test_signal() -> str:
    global _test_flip
    _test_flip = not _test_flip
    return "buy" if _test_flip else "sell"
