"""
tests/test_backend_no_mt5.py — El backend debe importar y operar sin MetaTrader5.

Simula un entorno Linux (sin los paquetes MetaTrader5/mt5linux) en un subproceso
con un import-blocker, e importa las capas clave del backend. Garantiza que el
core es broker-agnóstico: MT5 solo como adaptador opcional.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SCRIPT = r"""
import sys

class _BlockMT5:
    BLOCKED = {"MetaTrader5", "mt5linux"}
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in self.BLOCKED:
            raise ImportError(f"bloqueado para el test: {name}")
        return None

sys.meta_path.insert(0, _BlockMT5())
for mod in list(sys.modules):
    if mod.split(".")[0] in ("MetaTrader5", "mt5linux"):
        del sys.modules[mod]

# Capas que deben importar sin MT5
import backend.core.config
import backend.strategy.runtime
import backend.application
import backend.runtime.execution_engine
import backend.backtesting.runtime
import backend.analytics.trade_history
import backend.persistence
from backend.brokers.mt5_import import mt5
assert mt5 is None, "mt5 deberia ser None sin MetaTrader5 instalado"

# El broker paper debe funcionar de verdad sin MT5
from backend.brokers.factory import build_broker_adapter
broker = build_broker_adapter("paper")
broker.set_last_price("TEST", 100.0)
res = broker.apply_signal("TEST", "buy", 0.01, 0, 0, 12345, strategy_key="t")
assert res and res["actions"][-1]["success"], res
assert len(broker.get_open_positions("TEST", 12345)) == 1
assert build_broker_adapter("auto").__class__.__name__ == "PaperBrokerAdapter"
print("BACKEND_SIN_MT5_OK")
"""


def test_backend_imports_without_mt5():
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert "BACKEND_SIN_MT5_OK" in proc.stdout


if __name__ == "__main__":
    test_backend_imports_without_mt5()
    print("PASS test_backend_imports_without_mt5")
