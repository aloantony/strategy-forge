"""
tests/test_market_status.py — unit tests for trading.is_market_open().

Run with: python tests/test_market_status.py
"""

import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parent.parent
TRADING_PATH = ROOT / "trading.py"
sys.path.insert(0, str(ROOT))


def load_trading_module():
    fake_mt5 = types.SimpleNamespace(
        ORDER_FILLING_FOK=0,
        ORDER_FILLING_IOC=1,
        ORDER_FILLING_RETURN=2,
    )
    previous_mt5 = sys.modules.get("MetaTrader5")
    sys.modules["MetaTrader5"] = fake_mt5

    spec = importlib.util.spec_from_file_location("trading_test_module", TRADING_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake_mt5, previous_mt5


class MarketOpenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trading, cls.fake_mt5, cls.previous_mt5 = load_trading_module()

    @classmethod
    def tearDownClass(cls):
        if cls.previous_mt5 is None:
            sys.modules.pop("MetaTrader5", None)
        else:
            sys.modules["MetaTrader5"] = cls.previous_mt5

    def setUp(self):
        self.fake_mt5.symbol_info = lambda symbol: types.SimpleNamespace(trade_mode=1)

    @staticmethod
    def make_tick(dt_utc: datetime, bid: float = 100.0, ask: float = 100.2):
        return types.SimpleNamespace(
            time=int(dt_utc.timestamp()),
            bid=bid,
            ask=ask,
        )

    def test_recent_tick_is_open(self):
        now_utc = datetime.now(timezone.utc)
        self.fake_mt5.symbol_info_tick = lambda symbol: self.make_tick(now_utc - timedelta(seconds=5))

        market_open, status = self.trading.is_market_open("EURUSD")

        self.assertTrue(market_open)
        self.assertIn("Tick reciente", status)
        self.assertNotIn("compensado", status)

    def test_three_hour_future_tick_is_compensated(self):
        now_utc = datetime.now(timezone.utc)
        self.fake_mt5.symbol_info_tick = lambda symbol: self.make_tick(now_utc + timedelta(hours=3))

        market_open, status = self.trading.is_market_open("EURUSD")

        self.assertTrue(market_open)
        self.assertIn("offset broker +3h compensado", status)

    def test_non_hour_future_tick_remains_invalid(self):
        now_utc = datetime.now(timezone.utc)
        self.fake_mt5.symbol_info_tick = lambda symbol: self.make_tick(now_utc + timedelta(minutes=90))

        market_open, status = self.trading.is_market_open("EURUSD")

        self.assertFalse(market_open)
        self.assertIn("Hora de tick adelantada", status)


if __name__ == "__main__":
    unittest.main()
