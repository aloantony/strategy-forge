# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
backend/brokers/paper.py — Broker simulado en memoria (sin MT5).

Implementa IBrokerAdapter para entornos sin terminal de broker (Linux, tests,
desarrollo del servidor). No conecta con ningún mercado: mantiene posiciones en
memoria y rellena órdenes al precio indicado por el llamador (last_price) o 0.

No sustituye al backtesting (backend/backtesting) ni a un broker real; es el
adaptador por defecto cuando MT5 no está disponible.
"""

import itertools
import threading
import time
from typing import Optional

from backend.brokers.interface import (
    AccountInfo,
    IBrokerAdapter,
    InstrumentInfo,
    OrderResult,
)

_DIRECTION_BY_SIGNAL = {"buy": 1, "sell": -1}


class PaperBrokerAdapter(IBrokerAdapter):

    def __init__(self, initial_balance: float = 10_000.0, currency: str = "EUR"):
        self._lock = threading.Lock()
        self._balance = float(initial_balance)
        self._currency = currency
        self._positions: list[dict] = []
        self._ticket_seq = itertools.count(1)
        # Último precio conocido por símbolo; lo alimenta quien tenga datos (p.ej. el server).
        self.last_prices: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def set_last_price(self, symbol: str, price: float) -> None:
        self.last_prices[str(symbol)] = float(price)

    def _price(self, symbol: str) -> float:
        return float(self.last_prices.get(str(symbol), 0.0))

    # ------------------------------------------------------------------
    # Ejecución de órdenes
    # ------------------------------------------------------------------

    def send_order(self, symbol, order_type, lot, magic, sl_price, tp_price,
                   strategy_key="", strategy_label="", signal_reason="") -> OrderResult:
        price = self._price(symbol)
        with self._lock:
            ticket = next(self._ticket_seq)
            self._positions.append({
                "ticket": ticket,
                "symbol": str(symbol),
                "direction": 1 if int(order_type) == 0 else -1,
                "volume": float(lot),
                "price_open": price,
                "sl": float(sl_price or 0.0),
                "tp": float(tp_price or 0.0),
                "magic": int(magic),
                "strategy_key": strategy_key,
                "signal_reason": signal_reason,
                "time": int(time.time()),
            })
        return OrderResult(success=True, retcode=0, order_id=str(ticket),
                           deal_id=str(ticket), comment="paper fill",
                           price=price, volume=float(lot))

    def close_position(self, symbol, magic, strategy_key="", strategy_label="",
                       close_reason="") -> bool:
        price = self._price(symbol)
        with self._lock:
            remaining = []
            closed_any = False
            for pos in self._positions:
                if pos["symbol"] == str(symbol) and pos["magic"] == int(magic):
                    closed_any = True
                    if price and pos["price_open"]:
                        self._balance += (price - pos["price_open"]) * pos["direction"] * pos["volume"]
                else:
                    remaining.append(pos)
            self._positions = remaining
        return closed_any

    def modify_sl(self, symbol, magic, new_sl_price) -> bool:
        return self._modify_level(symbol, magic, "sl", new_sl_price)

    def modify_tp(self, symbol, magic, new_tp_price) -> bool:
        return self._modify_level(symbol, magic, "tp", new_tp_price)

    def _modify_level(self, symbol, magic, field: str, value) -> bool:
        with self._lock:
            touched = False
            for pos in self._positions:
                if pos["symbol"] == str(symbol) and pos["magic"] == int(magic):
                    pos[field] = float(value or 0.0)
                    touched = True
        return touched

    # ------------------------------------------------------------------
    # Señales de alto nivel
    # ------------------------------------------------------------------

    def apply_signal(self, symbol, signal, lot, sl_points, tp_points, magic_number,
                     strategy_key="", strategy_label="", signal_reason="") -> Optional[dict]:
        direction = _DIRECTION_BY_SIGNAL.get(str(signal or "").lower())
        if direction is None:
            return None
        current = self._current_direction(symbol, magic_number)
        actions = []
        if current == -direction:
            self.close_position(symbol, magic_number, strategy_key=strategy_key,
                                close_reason="reversal")
            actions.append({"kind": "close", "success": True})
        if current != direction:
            order_type = 0 if direction == 1 else 1
            result = self.send_order(symbol, order_type, lot, magic_number, 0.0, 0.0,
                                     strategy_key=strategy_key,
                                     signal_reason=signal_reason)
            actions.append({"kind": "open", "direction": signal, "success": result.success,
                            "ticket": result.order_id, "price": result.price,
                            "volume": result.volume})
        return {"symbol": symbol, "signal": signal, "strategy": strategy_key,
                "signal_reason": signal_reason, "actions": actions}

    def apply_pyramid_signal(self, symbol, magic_number, atr_value, lot,
                             strategy_key="", strategy_label="", signal_reason="",
                             balance=None, sl_atr_mult=1.0, tp_atr_mult=2.0,
                             pyramid_atr_mult=0.5, max_entries=None,
                             entry_index=None, direction=1) -> Optional[dict]:
        # Espejo del comportamiento de trading.apply_pyramid_signal (sin riesgo agregado):
        # entrada inicial o piramidada en la dirección indicada, SL/TP desde el ATR.
        direction = 1 if int(direction or 1) >= 0 else -1
        price = self._price(symbol)
        if atr_value <= 0 or price <= 0:
            return None

        positions = self.get_open_positions(symbol, magic_number)
        if max_entries is not None and max_entries > 0 and len(positions) >= max_entries:
            return None
        if entry_index is not None and entry_index >= 0 and len(positions) != entry_index:
            return None
        if positions:
            most_recent = positions[-1]
            if most_recent["direction"] != direction:
                return None
            threshold = most_recent["price_open"] + direction * (float(pyramid_atr_mult or 0.5) * atr_value)
            if direction == 1 and price < threshold:
                return None
            if direction == -1 and price > threshold:
                return None

        sl_price = price - direction * (float(sl_atr_mult or 1.0) * atr_value)
        tp_price = price + direction * (float(tp_atr_mult or 2.0) * atr_value)
        result = self.send_order(symbol, 0 if direction == 1 else 1, lot, magic_number,
                                 sl_price, tp_price,
                                 strategy_key=strategy_key, signal_reason=signal_reason)
        return {"symbol": symbol, "signal": "buy" if direction == 1 else "sell",
                "strategy": strategy_key, "pyramid": True,
                "actions": [{"kind": "pyramid_open", "success": result.success,
                             "ticket": result.order_id, "price": result.price}]}

    def _current_direction(self, symbol: str, magic: int) -> int:
        with self._lock:
            for pos in self._positions:
                if pos["symbol"] == str(symbol) and pos["magic"] == int(magic):
                    return int(pos["direction"])
        return 0

    # ------------------------------------------------------------------
    # Estado del mercado y cuenta
    # ------------------------------------------------------------------

    def is_market_open(self, symbol: str) -> tuple[bool, str]:
        return True, "Paper broker (mercado simulado siempre abierto)"

    def get_open_positions(self, symbol: str, magic_number: int) -> list[dict]:
        # magic_number <= 0 actúa como comodín: todas las posiciones del símbolo.
        with self._lock:
            return [dict(p) for p in self._positions
                    if p["symbol"] == str(symbol)
                    and (int(magic_number) <= 0 or p["magic"] == int(magic_number))]

    def get_account_info(self) -> Optional[AccountInfo]:
        with self._lock:
            return AccountInfo(balance=self._balance, equity=self._balance,
                               margin=0.0, free_margin=self._balance,
                               margin_level=0.0, currency=self._currency)

    def get_instrument_info(self, symbol: str) -> Optional[InstrumentInfo]:
        return InstrumentInfo(symbol=str(symbol), tick_size=0.01, tick_value=0.01,
                              point=0.01, digits=2, volume_min=0.01, volume_max=100.0,
                              volume_step=0.01, volume_digits=2, trade_stops_level=0,
                              trade_freeze_level=0, trade_fillings=1, filling_mode=1,
                              trade_exemode=1)
