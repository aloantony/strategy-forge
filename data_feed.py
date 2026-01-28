"""
Obtención y procesamiento de datos de mercado.
"""

import pandas as pd
import numpy as np
import MetaTrader5 as mt5
import config


def get_rates_df(symbol: str, timeframe, bars: int) -> pd.DataFrame:
    """
    Obtiene las velas históricas desde MetaTrader 5.
    
    Args:
        symbol: Símbolo a obtener.
        timeframe: Timeframe de MT5 (ej: mt5.TIMEFRAME_M1).
        bars: Número de velas a obtener.
    
    Returns:
        pd.DataFrame: DataFrame con columnas time, open, high, low, close.
    """
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        raise Exception(f"No se pudieron obtener datos para {symbol}")
    
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    return df


def add_source_columns(df: pd.DataFrame, source_mode: str) -> pd.DataFrame:
    """
    Calcula las columnas de fuente (OHLC4, HLC3, HL2, CLOSE) y H_Set, L_Set.
    
    Args:
        df: DataFrame con columnas open, high, low, close.
        source_mode: Modo de fuente ("OHLC4", "HLC3", "HL2", "CLOSE").
    
    Returns:
        pd.DataFrame: DataFrame con columnas adicionales.
    """
    df = df.copy()
    
    # Calcular todas las fuentes posibles
    df['OHLC4'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    df['HLC3'] = (df['high'] + df['low'] + df['close']) / 3
    df['HL2'] = (df['high'] + df['low']) / 2
    df['CLOSE'] = df['close']
    
    # Seleccionar H_Set y L_Set según source_mode
    if source_mode == "OHLC4":
        df['h_set'] = df['OHLC4']
        df['l_set'] = df['OHLC4']
    elif source_mode == "HLC3":
        df['h_set'] = df['HLC3']
        df['l_set'] = df['HLC3']
    elif source_mode == "HL2":
        df['h_set'] = df['HL2']
        df['l_set'] = df['HL2']
    elif source_mode == "CLOSE":
        df['h_set'] = df['CLOSE']
        df['l_set'] = df['CLOSE']
    else:
        raise ValueError(f"SOURCE_MODE no válido: {source_mode}")
    
    return df


def add_baseline_bands(df: pd.DataFrame, ma_length: int, atr_length: int, atr_mult: float) -> pd.DataFrame:
    """
    Calcula la media móvil (Average) y las bandas superior e inferior usando ATR.
    
    Args:
        df: DataFrame con columnas h_set, l_set.
        ma_length: Longitud de la media móvil.
        atr_length: Longitud del ATR.
        atr_mult: Multiplicador del ATR para las bandas.
    
    Returns:
        pd.DataFrame: DataFrame con columnas average, upper, lower.
    """
    df = df.copy()
    
    # Calcular Average (SMA sobre h_set como fuente)
    df['average'] = df['h_set'].rolling(window=ma_length).mean()
    
    # Calcular ATR clásico
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=atr_length).mean()
    
    # Calcular bandas
    df['upper'] = df['average'] + (df['atr'] * atr_mult)
    df['lower'] = df['average'] - (df['atr'] * atr_mult)
    
    return df


def weighted_moving_average(series: pd.Series, length: int) -> pd.Series:
    """
    Calcula la media móvil ponderada (WMA).
    """
    if length <= 1:
        return series
    weights = np.arange(1, length + 1, dtype=float)
    weight_sum = weights.sum()
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weight_sum, raw=True)


def hull_moving_average(series: pd.Series, length: int) -> pd.Series:
    """
    Calcula la media móvil de Hull (HMA).
    """
    if length <= 1:
        return series
    half_length = max(1, length // 2)
    sqrt_length = max(1, int(np.sqrt(length)))
    wma_half = weighted_moving_average(series, half_length)
    wma_full = weighted_moving_average(series, length)
    return weighted_moving_average(2 * wma_half - wma_full, sqrt_length)


def add_supertrend(
    df: pd.DataFrame,
    atr_length: int = 10,
    atr_mult: float = 3.0,
    source_col: str = "close",
    use_hma: bool = True,
    hma_length: int = 55
) -> pd.DataFrame:
    """
    Calcula el Supertrend (opcionalmente suavizado con HMA).

    Devuelve columnas:
      - supertrend
      - supertrend_dir (1 alcista, -1 bajista, 0 sin datos)
      - supertrend_up
      - supertrend_down
    """
    df = df.copy()

    # ATR específico para Supertrend (no sobrescribe el ATR base)
    atr_col = f"atr_st_{atr_length}"
    if atr_col not in df.columns or df[atr_col].isna().all():
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df[atr_col] = tr.rolling(window=atr_length).mean()

    atr = df[atr_col]

    source = df[source_col] if source_col in df.columns else df['close']
    if use_hma:
        df['hma'] = hull_moving_average(source, hma_length)
        price = df['hma']
    else:
        price = source

    hl2 = (df['high'] + df['low']) / 2
    basic_upper = hl2 + (atr_mult * atr)
    basic_lower = hl2 - (atr_mult * atr)

    final_upper = np.full(len(df), np.nan)
    final_lower = np.full(len(df), np.nan)
    supertrend = np.full(len(df), np.nan)
    direction = np.zeros(len(df))

    for i in range(len(df)):
        if pd.isna(atr.iloc[i]):
            continue

        if i == 0:
            final_upper[i] = basic_upper.iloc[i]
            final_lower[i] = basic_lower.iloc[i]
            continue

        prev_final_upper = final_upper[i - 1]
        prev_final_lower = final_lower[i - 1]
        if np.isnan(prev_final_upper):
            prev_final_upper = basic_upper.iloc[i - 1]
        if np.isnan(prev_final_lower):
            prev_final_lower = basic_lower.iloc[i - 1]

        prev_price = price.iloc[i - 1]

        if basic_upper.iloc[i] < prev_final_upper or prev_price > prev_final_upper:
            final_upper[i] = basic_upper.iloc[i]
        else:
            final_upper[i] = prev_final_upper

        if basic_lower.iloc[i] > prev_final_lower or prev_price < prev_final_lower:
            final_lower[i] = basic_lower.iloc[i]
        else:
            final_lower[i] = prev_final_lower

        prev_super = supertrend[i - 1]
        if np.isnan(prev_super):
            if price.iloc[i] >= final_lower[i]:
                supertrend[i] = final_lower[i]
                direction[i] = 1
            else:
                supertrend[i] = final_upper[i]
                direction[i] = -1
            continue

        if prev_super == prev_final_upper:
            if price.iloc[i] <= final_upper[i]:
                supertrend[i] = final_upper[i]
                direction[i] = -1
            else:
                supertrend[i] = final_lower[i]
                direction[i] = 1
        else:
            if price.iloc[i] >= final_lower[i]:
                supertrend[i] = final_lower[i]
                direction[i] = 1
            else:
                supertrend[i] = final_upper[i]
                direction[i] = -1

    df['supertrend'] = supertrend
    df['supertrend_dir'] = direction
    df['supertrend_up'] = np.where(df['supertrend_dir'] == 1, df['supertrend'], np.nan)
    df['supertrend_down'] = np.where(df['supertrend_dir'] == -1, df['supertrend'], np.nan)
    return df


def add_tci(
    df: pd.DataFrame,
    fast_length: int = 9,
    slow_length: int = 21,
    signal_length: int = 5,
    atr_col: str = "atr"
) -> pd.DataFrame:
    """
    Calcula un oscilador tipo TCI (normalizado por ATR o volatilidad).

    Devuelve columnas:
      - tci
      - tci_signal
      - tci_hist
    """
    df = df.copy()
    price = df['close']

    ema_fast = price.ewm(span=fast_length, adjust=False).mean()
    ema_slow = price.ewm(span=slow_length, adjust=False).mean()
    tci_raw = ema_fast - ema_slow

    if atr_col in df.columns and not df[atr_col].isna().all():
        denom = df[atr_col].replace(0, np.nan)
    else:
        denom = price.rolling(slow_length).std().replace(0, np.nan)

    tci = tci_raw / denom
    tci_signal = tci.ewm(span=signal_length, adjust=False).mean()
    tci_hist = tci - tci_signal

    df['tci'] = tci
    df['tci_signal'] = tci_signal
    df['tci_hist'] = tci_hist
    return df

