"""
Configuración del bot de trading.
Contiene todas las constantes de configuración.
"""

# Símbolo a operar
SYMBOL = "DE40"  # Placeholder para DAX

# Timeframe
TIMEFRAME = None  # Se establecerá como mt5.TIMEFRAME_M1 en main.py

# Historial de velas
BARS_HISTORY = 500

# Parámetros de trading
LOT = 0.01
SL_POINTS = 50.0
TP_POINTS = 100.0
MAGIC_NUMBER = 123456

# Configuración de la estrategia
SOURCE_MODE = "OHLC4"  # "OHLC4" | "HLC3" | "HL2" | "CLOSE"
MA_LENGTH = 20
ATR_LENGTH = 14
ATR_MULT = 2.0

# Habilitar señales
ENABLE_SIGNALS = True

# Intervalo de ejecución del bot (segundos)
SLEEP_SECONDS = 10


def print_config():
    """Imprime la configuración actual para depuración."""
    print("=== CONFIGURACIÓN ===")
    print(f"SYMBOL: {SYMBOL}")
    print(f"BARS_HISTORY: {BARS_HISTORY}")
    print(f"LOT: {LOT}")
    print(f"SL_POINTS: {SL_POINTS}")
    print(f"TP_POINTS: {TP_POINTS}")
    print(f"MAGIC_NUMBER: {MAGIC_NUMBER}")
    print(f"SOURCE_MODE: {SOURCE_MODE}")
    print(f"MA_LENGTH: {MA_LENGTH}")
    print(f"ATR_LENGTH: {ATR_LENGTH}")
    print(f"ATR_MULT: {ATR_MULT}")
    print(f"ENABLE_SIGNALS: {ENABLE_SIGNALS}")
    print(f"SLEEP_SECONDS: {SLEEP_SECONDS}")
    print("=====================")

