"""
Obtención y procesamiento de datos de mercado.
"""

import pandas as pd
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

