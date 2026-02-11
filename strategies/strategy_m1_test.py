"""
Estrategia simple para probar en M1.
EMA rapida vs EMA lenta con cruces en velas cerradas.
"""

from datetime import datetime
import pandas as pd


TIMEFRAME = "M1"

EMA_FAST = 9
EMA_SLOW = 21

DATA_WINDOW_FIELDS = [
    {"key": "ema_fast", "label": "EMA Fast (9)", "format": "price", "section": "EMA Cross"},
    {"key": "ema_slow", "label": "EMA Slow (21)", "format": "price", "section": "EMA Cross"},
    {"key": "ema_gap", "label": "EMA Gap", "format": "price", "section": "EMA Cross"},
]


def log_strategy(message: str):
    # Para peques: esta funcion sirve para escribir en el log estrategia.
    """Imprime mensaje de estrategia con timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [ESTRATEGIA] {message}")


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Para peques: esta funcion sirve para prepare dataframe.
    df = df.copy()
    if "close" not in df.columns:
        return df
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["ema_gap"] = df["ema_fast"] - df["ema_slow"]
    return df


def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    # Para peques: esta funcion sirve para obtener last senal.
    """
    Devuelve "buy", "sell" o "none".
    Usa la ultima vela cerrada: indice len(df) - 2.
    """
    if len(df) < 3:
        if verbose:
            log_strategy("Not enough data")
        return "none"

    last_idx = len(df) - 2
    prev_idx = last_idx - 1

    row = df.iloc[last_idx]
    prev = df.iloc[prev_idx]

    fast = row.get("ema_fast")
    slow = row.get("ema_slow")
    fast_prev = prev.get("ema_fast")
    slow_prev = prev.get("ema_slow")

    if any(pd.isna(v) for v in (fast, slow, fast_prev, slow_prev)):
        return "none"

    # Cruce al alza
    if fast_prev <= slow_prev and fast > slow:
        if verbose:
            log_strategy("Signal: BUY (EMA cross up)")
        return "buy"

    # Cruce a la baja
    if fast_prev >= slow_prev and fast < slow:
        if verbose:
            log_strategy("Signal: SELL (EMA cross down)")
        return "sell"

    return "none"
