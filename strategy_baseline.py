"""
Lógica de la estrategia de trading.
"""

import pandas as pd
import config


def compute_dir1_and_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:
    """
    Calcula Dir_1 y las señales Up_Sig y Dn_Sig.
    
    Args:
        df: DataFrame con columnas h_set, l_set, upper, lower.
        enable_signals: Si True, habilita las señales.
    
    Returns:
        pd.DataFrame: DataFrame con columnas dir1, up_sig, dn_sig.
    """
    df = df.copy()
    
    # Inicializar dir1
    df['dir1'] = 0
    
    # Calcular dir1 según la lógica:
    # - 1 si l_set > upper
    # - -1 si h_set < lower
    # - mantener valor anterior en otro caso
    for i in range(len(df)):
        if pd.isna(df.loc[i, 'upper']) or pd.isna(df.loc[i, 'lower']):
            df.loc[i, 'dir1'] = 0
        elif df.loc[i, 'l_set'] > df.loc[i, 'upper']:
            df.loc[i, 'dir1'] = 1
        elif df.loc[i, 'h_set'] < df.loc[i, 'lower']:
            df.loc[i, 'dir1'] = -1
        else:
            # Mantener valor anterior
            if i > 0:
                df.loc[i, 'dir1'] = df.loc[i-1, 'dir1']
            else:
                df.loc[i, 'dir1'] = 0
    
    # Calcular señales
    df['dir1_prev'] = df['dir1'].shift(1)
    df['dir1_prev'] = df['dir1_prev'].fillna(0)
    
    # Up_Sig: Dir_1 cambia a 1 desde un valor diferente
    df['up_sig'] = (df['dir1'] != df['dir1_prev']) & (df['dir1'] == 1) & enable_signals
    
    # Dn_Sig: Dir_1 cambia a -1 desde un valor diferente
    df['dn_sig'] = (df['dir1'] != df['dir1_prev']) & (df['dir1'] == -1) & enable_signals
    
    # Limpiar columna auxiliar
    df = df.drop(columns=['dir1_prev'])
    
    return df


def get_last_signal(df: pd.DataFrame) -> str:
    """
    Obtiene la última señal de la penúltima fila (última vela cerrada).
    
    Args:
        df: DataFrame con columnas up_sig, dn_sig.
    
    Returns:
        str: "buy", "sell" o "none".
    """
    if len(df) < 2:
        return "none"
    
    # Penúltima fila (última vela cerrada)
    last_closed_idx = len(df) - 2
    
    if df.loc[last_closed_idx, 'up_sig']:
        return "buy"
    elif df.loc[last_closed_idx, 'dn_sig']:
        return "sell"
    else:
        return "none"

