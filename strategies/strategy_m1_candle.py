"""
Estrategia simple para validar el flujo en M1.
Señal basada en el tamaño del cuerpo de la última vela cerrada.
"""

from datetime import datetime
import pandas as pd


TIMEFRAME = "M1"

# Tamaño mínimo del cuerpo para generar señal (en puntos)
MIN_BODY_POINTS = 40.0

DATA_WINDOW_FIELDS = [
    {"key": "body", "label": "Body", "format": "price", "section": "Candle Confirmed"},
    {"key": "body_points", "label": "Body Points", "format": "number", "section": "Candle Confirmed"},
    {"key": "min_body_points", "label": "Min Body Points", "format": "number", "section": "Candle Confirmed"},
]


def log_strategy(message: str):
    # Para peques: esta funcion sirve para escribir en el log estrategia.
    """Imprime mensaje de estrategia con timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [ESTRATEGIA] {message}")


def _get_points_multiplier(df: pd.DataFrame) -> float:
    # Para peques: esta funcion sirve para obtener points multiplier.
    """Convierte el tamaño del cuerpo a puntos según los dígitos del símbolo."""
    if df is None or len(df) == 0:
        return 1.0
    close = df["close"].iloc[-1]
    if not isinstance(close, (int, float)):
        return 1.0
    decimals = 0
    try:
        s = f"{close:.10f}"
        decimals = len(s.rstrip("0").split(".")[1])
    except Exception:
        decimals = 0
    return 10 ** decimals if decimals > 0 else 1.0


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Para peques: esta funcion sirve para prepare dataframe.
    df = df.copy()
    if "open" not in df.columns or "close" not in df.columns:
        return df
    multiplier = _get_points_multiplier(df)
    df["body"] = df["close"] - df["open"]
    df["body_points"] = df["body"].abs() * multiplier
    df["min_body_points"] = float(MIN_BODY_POINTS)
    return df


def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    # Para peques: esta funcion sirve para obtener last senal.
    """
    Devuelve "buy", "sell" o "none".
    Usa la última vela cerrada: índice len(df) - 2.
    """
    if len(df) < 2:
        if verbose:
            log_strategy("No hay suficientes datos")
        return "none"

    row = df.iloc[len(df) - 2]
    open_price = row.get("open")
    close_price = row.get("close")

    if not isinstance(open_price, (int, float)) or not isinstance(close_price, (int, float)):
        return "none"

    body = close_price - open_price
    points = abs(body) * _get_points_multiplier(df)

    if points >= MIN_BODY_POINTS:
        if body > 0:
            if verbose:
                log_strategy(f"BUY (cuerpo {points:.1f} pts)")
            return "buy"
        if body < 0:
            if verbose:
                log_strategy(f"SELL (cuerpo {points:.1f} pts)")
            return "sell"

    if verbose:
        log_strategy(f"NONE (cuerpo {points:.1f} pts)")
    return "none"
