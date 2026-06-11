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

# Historial de velas
BARS_HISTORY = 500

# Parámetros de trading
LOT = 0.01  # Tamaño mínimo para demo
SL_POINTS = 300.0  # Stop Loss en puntos (ajustado para DAX con spread de 200)
TP_POINTS = 500.0  # Take Profit en puntos (ajustado para DAX con spread de 200)
MAGIC_NUMBER = 123456

# Configuración de estrategias
STRATEGY_KEY = "ema_rsi_trend"
STRATEGY_MODULE = ""  # Opcional. Si esta vacio, se resuelve por convencion: strategies.strategy_<STRATEGY_KEY>
ACTIVE_STRATEGIES = []
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

# Escalado para muchas estrategias en vivo
STRATEGY_MAX_WORKERS = 8  # Hilos para análisis concurrente (0 = automático)
STRATEGY_ANALYSIS_TIMEOUT_SECONDS = 15  # Timeout total del análisis por ciclo
MAX_ORDERS_PER_ITERATION = 10  # Límite de órdenes enviadas por ciclo

# ---------------------------------------------------------------------------
# Supersistema v1
# ---------------------------------------------------------------------------
# PERSISTENCE_ENABLED: activa SQLite + migraciones al arrancar
PERSISTENCE_ENABLED = True

# PERSISTENCE_DB_PATH: ruta de la base de datos SQLite
PERSISTENCE_DB_PATH = "trading_bot.db"

# STRATEGY_RUNTIME_MODE:
#   "legacy"   -> comportamiento actual sin cambios (v1 no se usa)
#   "dual"     -> legacy + trazabilidad + adaptador v1 (recomendado durante transición)
#   "v1_only"  -> solo estrategias con decide() + STRATEGY_API_VERSION = 1
STRATEGY_RUNTIME_MODE = "v1_only"

# PLAN_EXECUTOR_ENABLED: si True, el ExecutionEngine interpreta y ejecuta planes v1.
# Si False, sigue usando trading.apply_signal() directamente.
PLAN_EXECUTOR_ENABLED = True

# CANONICAL_RESOURCES_ENABLED: activa persistencia de legs, entry_groups y fills.
CANONICAL_RESOURCES_ENABLED = True

# Strategy Builder v2 multi-timeframe support. Keep disabled to hide UI affordances
# while retaining schema/runtime compatibility for rollback.
ENABLE_BUILDER_MTF = False

# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------
# BROKER: adaptador de broker ("mt5" | "paper" | "auto"). "auto" usa MT5 si está
# disponible y paper en caso contrario. Sobreescribible con env TRADING_BROKER.
BROKER = "auto"

