"""
Strategy to stress-test Strategy Data and Data Window with multiple metrics.
Combines trend, momentum, volatility, and volume filters.
"""

from datetime import datetime
import pandas as pd


TIMEFRAME = "M1"
MAGIC_NUMBER = 50321019

# Core parameters
EMA_FAST = 12
EMA_SLOW = 34
RSI_LENGTH = 14
ATR_LENGTH = 14
MOMENTUM_LENGTH = 3
VOLATILITY_LENGTH = 20
VOLUME_LOOKBACK = 20

# Signal thresholds
RSI_LONG_MIN = 55.0
RSI_SHORT_MAX = 45.0
MIN_VOLUME_RATIO = 0.90
TREND_SCORE_MIN = 0.20
TREND_SCORE_ENTRY = 0.35


# Keep the default indicator groups visible/toggleable in the GUI
OBJECT_TREE_ITEMS = ["baseline", "atr_bands", "supertrend", "tci"]


# Rich Data Window payload for testing
DATA_WINDOW_FIELDS = [
    {"key": "ema_fast", "label": "EMA Fast (12)", "format": "price", "section": "Trend", "group": "baseline"},
    {"key": "ema_slow", "label": "EMA Slow (34)", "format": "price", "section": "Trend", "group": "baseline"},
    {"key": "ema_spread", "label": "EMA Spread", "format": "price", "section": "Trend", "group": "baseline"},
    {"key": "trend_state", "label": "Trend State", "format": "int", "section": "Trend"},
    {"key": "rsi_14", "label": "RSI 14", "format": "number", "section": "Momentum"},
    {"key": "momentum_3", "label": "Momentum 3", "format": "percent", "section": "Momentum"},
    {"key": "tci_delta", "label": "TCI Delta", "format": "number", "section": "Momentum", "group": "tci"},
    {"key": "atr_14", "label": "ATR 14", "format": "price", "section": "Volatility", "group": "atr_bands"},
    {"key": "atr_pct", "label": "ATR %", "format": "percent", "section": "Volatility", "group": "atr_bands"},
    {"key": "volatility_20", "label": "Volatility 20", "format": "percent", "section": "Volatility"},
    {"key": "volume_ratio", "label": "Volume Ratio", "format": "number", "section": "Volume"},
    {"key": "baseline_gap", "label": "Baseline Gap", "format": "percent", "section": "Context", "group": "baseline"},
    {"key": "supertrend_bias", "label": "Supertrend Bias", "format": "int", "section": "Context", "group": "supertrend"},
    {"key": "trend_score", "label": "Trend Score", "format": "number", "section": "Composite"},
    {"key": "long_setup", "label": "Long Setup", "format": "int", "section": "Signals", "shift": 1},
    {"key": "short_setup", "label": "Short Setup", "format": "int", "section": "Signals", "shift": 1},
    {"key": "up_sig", "label": "Buy Signal", "format": "int", "section": "Signals", "shift": 1},
    {"key": "dn_sig", "label": "Sell Signal", "format": "int", "section": "Signals", "shift": 1},
]


_test_flip = False


def log_strategy(message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [STRATEGY_MULTI] {message}")


def _empty_float(index):
    return pd.Series(float("nan"), index=index, dtype="float64")


def _numeric_column(df: pd.DataFrame, key: str):
    if key in df.columns:
        return pd.to_numeric(df[key], errors="coerce")
    return _empty_float(df.index)


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


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
    df = df.copy()
    required = {"high", "low", "close"}
    if not required.issubset(df.columns):
        return df

    close = _numeric_column(df, "close")
    high = _numeric_column(df, "high")
    low = _numeric_column(df, "low")

    if "tick_volume" in df.columns:
        volume = _numeric_column(df, "tick_volume")
    elif "volume" in df.columns:
        volume = _numeric_column(df, "volume")
    else:
        volume = pd.Series(1.0, index=df.index, dtype="float64")

    ema_fast = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()
    ema_spread = ema_fast - ema_slow
    trend_state = (ema_fast > ema_slow).astype(int) - (ema_fast < ema_slow).astype(int)

    rsi_14 = _rsi(close, RSI_LENGTH)
    atr_14 = _atr(high, low, close, ATR_LENGTH)
    atr_pct = atr_14 / close.replace(0.0, float("nan"))

    returns = close.pct_change()
    volatility_20 = returns.rolling(VOLATILITY_LENGTH, min_periods=VOLATILITY_LENGTH).std()
    momentum_3 = close.pct_change(MOMENTUM_LENGTH)

    volume_ma = volume.rolling(VOLUME_LOOKBACK, min_periods=5).mean()
    volume_ratio = volume / volume_ma.replace(0.0, float("nan"))

    average = _numeric_column(df, "average")
    baseline_gap = (close - average) / close.replace(0.0, float("nan"))

    st_up = _numeric_column(df, "supertrend_up")
    st_down = _numeric_column(df, "supertrend_down")
    supertrend_bias = pd.Series(0, index=df.index, dtype="int64")
    supertrend_bias = supertrend_bias.mask(st_up.notna(), 1)
    supertrend_bias = supertrend_bias.mask(st_down.notna(), -1)

    tci_hist = _numeric_column(df, "tci_hist")
    tci_signal = _numeric_column(df, "tci_signal")
    tci_delta = tci_hist - tci_signal

    ema_component = (ema_spread / atr_14.replace(0.0, float("nan"))).clip(-3.0, 3.0) / 3.0
    rsi_component = ((rsi_14 - 50.0) / 50.0).clip(-1.0, 1.0)
    momentum_component = (momentum_3 * 10.0).clip(-1.0, 1.0)
    volume_component = (volume_ratio - 1.0).clip(-1.0, 1.0)
    supertrend_component = supertrend_bias.clip(-1, 1).astype("float64")
    tci_component = (tci_delta / 10.0).clip(-1.0, 1.0)

    trend_score = (
        0.30 * ema_component.fillna(0.0)
        + 0.20 * rsi_component.fillna(0.0)
        + 0.15 * momentum_component.fillna(0.0)
        + 0.15 * volume_component.fillna(0.0)
        + 0.10 * supertrend_component.fillna(0.0)
        + 0.10 * tci_component.fillna(0.0)
    )

    df["ema_fast"] = ema_fast
    df["ema_slow"] = ema_slow
    df["ema_spread"] = ema_spread
    df["trend_state"] = trend_state
    df["rsi_14"] = rsi_14
    df["atr_14"] = atr_14
    df["atr_pct"] = atr_pct
    df["volatility_20"] = volatility_20
    df["momentum_3"] = momentum_3
    df["volume_ratio"] = volume_ratio
    df["baseline_gap"] = baseline_gap
    df["supertrend_bias"] = supertrend_bias
    df["tci_delta"] = tci_delta
    df["trend_score"] = trend_score

    return df


def compute_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:
    df = df.copy()
    needed = {
        "ema_fast",
        "ema_slow",
        "rsi_14",
        "momentum_3",
        "volume_ratio",
        "trend_score",
    }
    if not needed.issubset(df.columns):
        df["long_setup"] = 0
        df["short_setup"] = 0
        df["up_sig"] = 0
        df["dn_sig"] = 0
        return df

    ema_fast = pd.to_numeric(df["ema_fast"], errors="coerce")
    ema_slow = pd.to_numeric(df["ema_slow"], errors="coerce")
    rsi_14 = pd.to_numeric(df["rsi_14"], errors="coerce")
    momentum_3 = pd.to_numeric(df["momentum_3"], errors="coerce")
    volume_ratio = pd.to_numeric(df["volume_ratio"], errors="coerce")
    trend_score = pd.to_numeric(df["trend_score"], errors="coerce")

    close = _numeric_column(df, "close")
    average = _numeric_column(df, "average")
    supertrend_bias = pd.to_numeric(df.get("supertrend_bias"), errors="coerce")
    tci_delta = pd.to_numeric(df.get("tci_delta"), errors="coerce")

    long_setup = (
        (ema_fast > ema_slow)
        & (close >= average)
        & (rsi_14 >= RSI_LONG_MIN)
        & (momentum_3 > 0.0)
        & (volume_ratio >= MIN_VOLUME_RATIO)
        & (trend_score >= TREND_SCORE_MIN)
        & (supertrend_bias >= 0.0)
        & (tci_delta > 0.0)
    )
    short_setup = (
        (ema_fast < ema_slow)
        & (close <= average)
        & (rsi_14 <= RSI_SHORT_MAX)
        & (momentum_3 < 0.0)
        & (volume_ratio >= MIN_VOLUME_RATIO)
        & (trend_score <= -TREND_SCORE_MIN)
        & (supertrend_bias <= 0.0)
        & (tci_delta < 0.0)
    )

    ema_cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
    ema_cross_down = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))
    score_cross_up = (trend_score >= TREND_SCORE_ENTRY) & (trend_score.shift(1) < TREND_SCORE_ENTRY)
    score_cross_down = (trend_score <= -TREND_SCORE_ENTRY) & (trend_score.shift(1) > -TREND_SCORE_ENTRY)

    if enable_signals:
        buy_signal = long_setup & (ema_cross_up | score_cross_up)
        sell_signal = short_setup & (ema_cross_down | score_cross_down)
    else:
        buy_signal = pd.Series(False, index=df.index)
        sell_signal = pd.Series(False, index=df.index)

    df["long_setup"] = long_setup.astype(int)
    df["short_setup"] = short_setup.astype(int)
    df["up_sig"] = buy_signal.astype(int)
    df["dn_sig"] = sell_signal.astype(int)
    return df


def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    if df is None or len(df) < 3:
        if verbose:
            log_strategy("Not enough data")
        return "none"

    row = df.iloc[len(df) - 2]
    buy = bool(int(row.get("up_sig", 0) or 0))
    sell = bool(int(row.get("dn_sig", 0) or 0))

    if verbose:
        score = row.get("trend_score")
        rsi = row.get("rsi_14")
        vol_ratio = row.get("volume_ratio")
        log_strategy(f"score={score:.3f} rsi={rsi:.2f} vol_ratio={vol_ratio:.2f}")

    if buy and not sell:
        return "buy"
    if sell and not buy:
        return "sell"
    return "none"


def get_test_signal() -> str:
    global _test_flip
    _test_flip = not _test_flip
    return "buy" if _test_flip else "sell"
