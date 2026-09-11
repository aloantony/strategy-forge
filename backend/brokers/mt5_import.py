# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

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
