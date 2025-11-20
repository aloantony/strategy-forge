from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, List


@dataclass
class Candle:
    symbol: str
    timeframe: str  # e.g. "3m"
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    open_time: datetime
    close_time: datetime


class BrokerAPI(ABC):
    @abstractmethod
    async def connect(self) -> None:
        """Establish any necessary sessions, auth, websockets, etc."""
        raise NotImplementedError

    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
    ) -> List[Candle]:
        """Return up to `limit` closed candles, ordered by time ascending."""
        raise NotImplementedError

    @abstractmethod
    async def stream_candles(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Candle]:
        """
        Yield closed candles in real time for the given symbol and timeframe.
        Internally this can transform raw ticks or lower-timeframe bars into
        higher timeframes.
        """
        raise NotImplementedError

