# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
Procesamiento de datos de mercado: columnas de fuente e indicadores derivados.
Módulo puro (pandas/numpy, sin broker); la obtención de velas vive en las
implementaciones de IDataFeed/IHistoricalDataSource (p.ej. mt5_data_feed.py).
"""

import pandas as pd
import numpy as np


def add_source_columns(df: pd.DataFrame, source_mode: str) -> pd.DataFrame:
    # creamos "precios resumidos" (OHLC4, HLC3...) para que la estrategia elija uno.
    """
    Calcula las columnas de fuente (OHLC4, HLC3, HL2, CLOSE) y H_Set, L_Set.
    
    Args:
        df: DataFrame con columnas open, high, low, close.
        source_mode: Modo de fuente ("OHLC4", "HLC3", "HL2", "CLOSE").
    
    Returns:
        pd.DataFrame: DataFrame con columnas adicionales.
    """
    df = df.copy()
    
    # Calculamos varias formas de resumir el precio de cada vela.
    df['OHLC4'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    df['HLC3'] = (df['high'] + df['low'] + df['close']) / 3
    df['HL2'] = (df['high'] + df['low']) / 2
    df['CLOSE'] = df['close']
    
    # Segun SOURCE_MODE, elegimos cual de esos resúmenes sera la base de la estrategia.
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
    # dibujamos una linea central y dos "barandillas" arriba y abajo.
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
    
    # ATR mide cuanto se mueve el precio; lo usamos para separar las barandillas.
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=atr_length).mean()
    
    # Upper y Lower son limites dinamicos alrededor de la media.
    df['upper'] = df['average'] + (df['atr'] * atr_mult)
    df['lower'] = df['average'] - (df['atr'] * atr_mult)
    
    return df


def weighted_moving_average(series: pd.Series, length: int) -> pd.Series:
    # esta media da mas importancia a los datos mas recientes.
    """
    Calcula la media móvil ponderada (WMA).
    """
    if length <= 1:
        return series
    weights = np.arange(1, length + 1, dtype=float)
    weight_sum = weights.sum()
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weight_sum, raw=True)


def hull_moving_average(series: pd.Series, length: int) -> pd.Series:
    # HMA intenta ser suave como una media, pero reaccionar mas rapido.
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
    # calculamos una guia de tendencia que va cambiando de lado del precio.
    """
    Calcula el Supertrend (opcionalmente suavizado con HMA).

    Devuelve columnas:
      - supertrend
      - supertrend_dir (1 alcista, -1 bajista, 0 sin datos)
      - supertrend_up
      - supertrend_down
    """
    df = df.copy()

    # Usamos un ATR propio para Supertrend, separado del ATR base.
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
        # Si se activa HMA, usamos un precio suavizado para evitar ruido.
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

    # Recorremos vela por vela para decidir si la tendencia sigue o cambia.
    for i in range(len(df)):
        if pd.isna(atr.iloc[i]):
            continue

        if i == 0:
            # Primera vela valida: solo sembramos valores iniciales.
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

        # Si antes estabamos "arriba", verificamos si toca seguir arriba o cruzar abajo (y viceversa).
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
    # creamos un oscilador para saber si el impulso sube o baja.
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

    # Normalizamos por ATR (o por desviacion) para comparar mejor entre momentos de distinta volatilidad.
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


