"""
Configuración del bot de trading.
Contiene todas las constantes de configuración.
"""

# Símbolo a operar
SYMBOL = "#Germany40"  # DAX Spot Index CFD - FxPro (requiere prefijo #)
# SYMBOL = "#GER40_Z25"  # DAX Future Dec 2025
# SYMBOL = "DE40"  # DAX (otros brokers)
# SYMBOL = "EURUSD"  # Forex - abierto 24/5

# Timeframe
TIMEFRAME = None  # Se establecerá como mt5.TIMEFRAME_M1 en main.py

# Modo de pruebas: fuerza señales para validar ejecuciones
TEST_MODE = False  # Si True, alterna BUY/SELL en cada iteración (desactivado para demo real)

# Historial de velas
BARS_HISTORY = 500

# Parámetros de trading
LOT = 0.01  # Tamaño mínimo para demo
SL_POINTS = 300.0  # Stop Loss en puntos (ajustado para DAX con spread de 200)
TP_POINTS = 500.0  # Take Profit en puntos (ajustado para DAX con spread de 200)
MAGIC_NUMBER = 123456

# Configuración de la estrategia
STRATEGY_KEY = "baseline"
STRATEGY_MODULE = "strategies.strategy_baseline"
ACTIVE_STRATEGIES = [STRATEGY_KEY]
STRATEGY_DIR = "strategies"
SOURCE_MODE = "OHLC4"  # "OHLC4" | "HLC3" | "HL2" | "CLOSE"
MA_LENGTH = 20
ATR_LENGTH = 14
ATR_MULT = 0.5  # Reducido de 2.0 para generar señales más frecuentes

# Indicadores extra (solo visualización en la interfaz)
SUPERTREND_ATR_LENGTH = 10
SUPERTREND_MULT = 3.0
SUPERTREND_SOURCE = "close"  # close | h_set | l_set | OHLC4
SUPERTREND_USE_HMA = True
HMA_LENGTH = 55

TCI_FAST = 9
TCI_SLOW = 21
TCI_SIGNAL = 5

# Habilitar señales
ENABLE_SIGNALS = True

# Intervalo de ejecución del bot (segundos)
SLEEP_SECONDS = 10

# Feedback / sugerencias
# Si FEEDBACK_WEBHOOK_URL tiene un valor, se enviará un POST con JSON.
# Si no, se guardará en un archivo local en FEEDBACK_SAVE_DIR.
FEEDBACK_WEBHOOK_URL = "https://outside-adelheid-bralsolving-397f3acf.koyeb.app/feedback?key=98679247c1d14aea9d11cf16fd9482cf"
FEEDBACK_SAVE_DIR = "feedback"
FEEDBACK_TIMEOUT_SECONDS = 4
FEEDBACK_LIST_URL = ""


def print_config():
    # Para peques: esta funcion sirve para mostrar config.
    """Imprime la configuración actual para depuración."""
    print("=== CONFIGURACIÓN ===")
    print(f"SYMBOL: {SYMBOL}")
    print(f"BARS_HISTORY: {BARS_HISTORY}")
    print(f"LOT: {LOT}")
    print(f"SL_POINTS: {SL_POINTS}")
    print(f"TP_POINTS: {TP_POINTS}")
    print(f"MAGIC_NUMBER: {MAGIC_NUMBER}")
    print(f"STRATEGY_KEY: {STRATEGY_KEY}")
    print(f"STRATEGY_MODULE: {STRATEGY_MODULE}")
    print(f"ACTIVE_STRATEGIES: {ACTIVE_STRATEGIES}")
    print(f"STRATEGY_DIR: {STRATEGY_DIR}")
    print(f"SOURCE_MODE: {SOURCE_MODE}")
    print(f"MA_LENGTH: {MA_LENGTH}")
    print(f"ATR_LENGTH: {ATR_LENGTH}")
    print(f"ATR_MULT: {ATR_MULT}")
    print(f"SUPERTREND_ATR_LENGTH: {SUPERTREND_ATR_LENGTH}")
    print(f"SUPERTREND_MULT: {SUPERTREND_MULT}")
    print(f"SUPERTREND_SOURCE: {SUPERTREND_SOURCE}")
    print(f"SUPERTREND_USE_HMA: {SUPERTREND_USE_HMA}")
    print(f"HMA_LENGTH: {HMA_LENGTH}")
    print(f"TCI_FAST: {TCI_FAST}")
    print(f"TCI_SLOW: {TCI_SLOW}")
    print(f"TCI_SIGNAL: {TCI_SIGNAL}")
    print(f"ENABLE_SIGNALS: {ENABLE_SIGNALS}")
    print(f"SLEEP_SECONDS: {SLEEP_SECONDS}")
    print("=====================")
