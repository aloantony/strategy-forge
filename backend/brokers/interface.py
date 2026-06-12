from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class InstrumentInfo:
    symbol: str
    tick_size: float
    tick_value: float
    point: float
    digits: int
    volume_min: float
    volume_max: float
    volume_step: float
    volume_digits: int
    trade_stops_level: int
    trade_freeze_level: int
    trade_fillings: int
    filling_mode: int
    trade_exemode: int


@dataclass
class OrderResult:
    success: bool
    retcode: int
    order_id: str
    deal_id: str
    comment: str
    price: float = 0.0
    volume: float = 0.0


@dataclass
class AccountInfo:
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str


class IBrokerAdapter(ABC):

    # ------------------------------------------------------------------
    # Ejecución de órdenes (usadas por ExecutionEngine)
    # ------------------------------------------------------------------

    @abstractmethod
    def send_order(
        self,
        symbol: str,
        order_type: int,
        lot: float,
        magic: int,
        sl_price: float,
        tp_price: float,
        strategy_key: str = "",
        strategy_label: str = "",
        signal_reason: str = "",
    ) -> OrderResult:
        ...

    @abstractmethod
    def close_position(
        self,
        symbol: str,
        magic: int,
        strategy_key: str = "",
        strategy_label: str = "",
        close_reason: str = "",
    ) -> bool:
        ...

    @abstractmethod
    def modify_sl(
        self,
        symbol: str,
        magic: int,
        new_sl_price: float,
    ) -> bool:
        ...

    @abstractmethod
    def modify_tp(
        self,
        symbol: str,
        magic: int,
        new_tp_price: float,
    ) -> bool:
        ...

    # ------------------------------------------------------------------
    # Señales de alto nivel (usadas por main.py y gui_charts.py)
    # ------------------------------------------------------------------

    @abstractmethod
    def apply_signal(
        self,
        symbol: str,
        signal: str,
        lot: float,
        sl_points: float,
        tp_points: float,
        magic_number: int,
        strategy_key: str = "",
        strategy_label: str = "",
        signal_reason: str = "",
    ) -> Optional[dict]:
        ...

    @abstractmethod
    def apply_pyramid_signal(
        self,
        symbol: str,
        magic_number: int,
        atr_value: float,
        lot: float,
        strategy_key: str = "",
        strategy_label: str = "",
        signal_reason: str = "",
        balance: Optional[float] = None,
        sl_atr_mult: float = 1.0,
        tp_atr_mult: float = 2.0,
        pyramid_atr_mult: float = 0.5,
        max_entries: Optional[int] = None,
        entry_index: Optional[int] = None,
        direction: int = 1,
    ) -> Optional[dict]:
        ...

    # ------------------------------------------------------------------
    # Estado del mercado y cuenta (usadas por main.py, gui_charts.py)
    # ------------------------------------------------------------------

    @abstractmethod
    def is_market_open(self, symbol: str) -> tuple[bool, str]:
        ...

    @abstractmethod
    def get_open_positions(self, symbol: str, magic_number: int) -> list[dict]:
        ...

    @abstractmethod
    def get_account_info(self) -> Optional[AccountInfo]:
        ...

    @abstractmethod
    def get_instrument_info(self, symbol: str) -> Optional[InstrumentInfo]:
        ...
