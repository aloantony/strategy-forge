"""
Lógica de la estrategia de trading.
"""

import pandas as pd
from datetime import datetime


def log_strategy(message: str):
    # Para peques: esta funcion sirve para escribir en el log estrategia.
    """Imprime mensaje de estrategia con timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [ESTRATEGIA] {message}")


# Timeframe sobre el que opera esta estrategia (usado por la GUI)
TIMEFRAME = "M1"

# Indicadores usados por la estrategia (GUI Object Tree)
OBJECT_TREE_ITEMS = ["baseline", "atr_bands"]

# Campos recomendados para el Data Window de esta estrategia
DATA_WINDOW_FIELDS = [
    {"key": "h_set", "label": "H_Set", "format": "price", "section": "Estrategia"},
    {"key": "l_set", "label": "L_Set", "format": "price", "section": "Estrategia"},
    {"key": "average", "label": "Average", "format": "price", "section": "Baseline", "group": "baseline"},
    {"key": "upper", "label": "Upper", "format": "price", "section": "ATR Bands", "group": "atr_bands"},
    {"key": "lower", "label": "Lower", "format": "price", "section": "ATR Bands", "group": "atr_bands"},
    {"key": "dir1", "label": "Dir_1", "format": "number", "section": "Senales"},
    {"key": "up_sig", "label": "Up_Sig", "format": "number", "section": "Senales"},
    {"key": "dn_sig", "label": "Dn_Sig", "format": "number", "section": "Senales"},
]


def compute_dir1_and_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:
    # Para peques: esta funcion sirve para compute dir1 and senales.
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


# --- Modo de prueba: alternar señales para validar ejecuciones ---
_test_flip = False


def get_test_signal() -> str:
    # Para peques: esta funcion sirve para obtener test senal.
    """Alterna BUY/SELL en cada llamada para probar ejecuciones."""
    global _test_flip
    _test_flip = not _test_flip
    return "buy" if _test_flip else "sell"


def get_last_signal(df: pd.DataFrame, verbose: bool = True) -> str:
    # Para peques: esta funcion sirve para obtener last senal.
    """
    Obtiene la señal basada en la dirección actual de Dir_1.
    
    MODO MVP/DEMO: Genera señal basada en la tendencia actual,
    no solo cuando hay cambio de dirección.
    
    Args:
        df: DataFrame con columnas dir1.
        verbose: Si True, imprime información detallada.
    
    Returns:
        str: "buy", "sell" o "none".
    """
    if len(df) < 2:
        if verbose:
            log_strategy("No hay suficientes datos (< 2 velas)")
        return "none"
    
    # Penúltima fila (última vela cerrada)
    last_closed_idx = len(df) - 2
    row = df.iloc[last_closed_idx]
    
    if verbose:
        # Mostrar análisis detallado
        print("\n" + "="*60)
        log_strategy("ANALISIS DE SENALES (MODO MVP)")
        print("="*60)
        print(f"   [VELA] Analizada: {row['time']}")
        print(f"   [PRECIO] OHLC4: {row['h_set']:.2f}")
        print(f"   [UPPER] Banda superior: {row['upper']:.2f}")
        print(f"   [LOWER] Banda inferior: {row['lower']:.2f}")
        print(f"   [MA] Average: {row['average']:.2f}")
        print()
        
        # Estado de Dir_1
        dir1_current = row['dir1']
        dir1_names = {1: "ALCISTA (+1)", -1: "BAJISTA (-1)", 0: "NEUTRAL (0)"}
        print(f"   [DIR1] Direccion actual: {dir1_names.get(dir1_current, dir1_current)}")
        print()
    
    # MODO MVP: Señal basada en dirección actual
    dir1_current = row['dir1']
    
    if dir1_current == 1:
        if verbose:
            log_strategy(">>> SENAL BUY - Tendencia ALCISTA <<<")
        return "buy"
    elif dir1_current == -1:
        if verbose:
            log_strategy(">>> SENAL SELL - Tendencia BAJISTA <<<")
        return "sell"
    else:
        if verbose:
            log_strategy("Sin senal - Tendencia NEUTRAL")
        return "none"
