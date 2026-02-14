"""
Scalping M1:
Breakout corto con canal Donchian + volumen + filtro EMA.
"""

from datetime import datetime
import pandas as pd


TIMEFRAME = "M1"

DONCHIAN_LENGTH = 12
EMA_FILTER = 34
ATR_LENGTH = 14
VOL_LOOKBACK = 24
MIN_ATR_PCT = 0.00005
MIN_VOLUME_RATIO = 1.05


DATA_WINDOW_FIELDS = [
    {"key": "donchian_high", "label": "Donchian High (12)", "format": "price", "section": "Donchian"},
    {"key": "donchian_low", "label": "Donchian Low (12)", "format": "price", "section": "Donchian"},
    {"key": "donchian_mid", "label": "Donchian Mid", "format": "price", "section": "Donchian"},
    {"key": "ema_filter", "label": "EMA Filter (34)", "format": "price", "section": "Trend"},
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
    print(f"[{timestamp}] [SCALP_DONCHIAN] {message}")


def _numeric(df: pd.DataFrame, key: str) -> pd.Series:
    return pd.to_numeric(df.get(key), errors="coerce")


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


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    required = {"high", "low", "close"}
    if not required.issubset(out.columns):
        return out

    high = _numeric(out, "high")
    low = _numeric(out, "low")
    close = _numeric(out, "close")

    if "tick_volume" in out.columns:
        volume = _numeric(out, "tick_volume")
    elif "volume" in out.columns:
        volume = _numeric(out, "volume")
    else:
        volume = pd.Series(1.0, index=out.index, dtype="float64")

    donchian_high = high.rolling(DONCHIAN_LENGTH, min_periods=DONCHIAN_LENGTH).max().shift(1)
    donchian_low = low.rolling(DONCHIAN_LENGTH, min_periods=DONCHIAN_LENGTH).min().shift(1)
    donchian_mid = (donchian_high + donchian_low) / 2.0

    ema_filter = close.ewm(span=EMA_FILTER, adjust=False).mean()
    atr_14 = _atr(high, low, close, ATR_LENGTH)
    atr_pct = atr_14 / close.replace(0.0, float("nan"))
    vol_ma = volume.rolling(VOL_LOOKBACK, min_periods=5).mean()
    volume_ratio = volume / vol_ma.replace(0.0, float("nan"))

    out["donchian_high"] = donchian_high
    out["donchian_low"] = donchian_low
    out["donchian_mid"] = donchian_mid
    out["ema_filter"] = ema_filter
    out["atr_14"] = atr_14
    out["atr_pct"] = atr_pct
    out["volume_ratio"] = volume_ratio
    return out


def compute_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:
    out = df.copy()
    needed = {
        "close",
        "donchian_high",
        "donchian_low",
        "ema_filter",
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
    donchian_high = _numeric(out, "donchian_high")
    donchian_low = _numeric(out, "donchian_low")
    ema_filter = _numeric(out, "ema_filter")
    atr_pct = _numeric(out, "atr_pct")
    volume_ratio = _numeric(out, "volume_ratio")

    valid_channel = donchian_high.notna() & donchian_low.notna()
    enough_activity = (atr_pct >= MIN_ATR_PCT) & (volume_ratio >= MIN_VOLUME_RATIO)

    breakout_up = (close > donchian_high) & (close.shift(1) <= donchian_high.shift(1))
    breakout_down = (close < donchian_low) & (close.shift(1) >= donchian_low.shift(1))

    long_setup = valid_channel & enough_activity & (close >= ema_filter) & breakout_up
    short_setup = valid_channel & enough_activity & (close <= ema_filter) & breakout_down

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
            log_strategy("BUY: breakout M1")
        return {"signal": "buy", "reason": "Scalp breakout: ruptura Donchian 12 + volumen"}
    if sell and not buy:
        if verbose:
            log_strategy("SELL: breakout M1")
        return {"signal": "sell", "reason": "Scalp breakout: ruptura bajista Donchian 12 + volumen"}
    return {"signal": "none", "reason": "Sin ruptura valida M1"}


def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    payload = get_last_signal_payload(df, verbose=verbose)
    return payload.get("signal", "none")
