"""
Import condicional de MetaTrader5 según plataforma.
- Windows: usa MetaTrader5 oficial (acceso directo al terminal local).
- Mac/Linux: usa mt5linux (proxy ZeroMQ hacia un Windows remoto con MT5).
"""
import sys

mt5 = None

if sys.platform == "win32":
    try:
        import MetaTrader5 as mt5
    except ImportError:
        mt5 = None
else:
    try:
        from mt5linux import MetaTrader5 as _MT5Class
        import config as _config
        mt5 = _MT5Class(
            host=getattr(_config, "MT5LINUX_HOST", "localhost"),
            port=int(getattr(_config, "MT5LINUX_PORT", 18812)),
        )
    except ImportError:
        mt5 = None
