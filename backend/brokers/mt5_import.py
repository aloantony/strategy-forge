"""
Import condicional de MetaTrader5.
- Windows con el paquete instalado: módulo oficial (acceso al terminal local).
- Resto de entornos (Linux/servidores): mt5 = None; el backend opera con el
  broker `paper` u otros adaptadores vía backend.brokers.factory.
"""
import sys

mt5 = None

if sys.platform == "win32":
    try:
        import MetaTrader5 as mt5
    except ImportError:
        mt5 = None
