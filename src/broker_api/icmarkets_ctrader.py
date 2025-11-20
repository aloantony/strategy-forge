from __future__ import annotations

import asyncio
import logging
import os
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Dict, List, Optional

from ctrader_open_api.messages import (
    OpenApiCommonMessages_pb2 as common,
    OpenApiMessages_pb2 as oa,
    OpenApiModelMessages_pb2 as model,
)
from ctrader_open_api.protobuf import Protobuf

from .aggregation import TIMEFRAME_TO_MINUTES, aggregate_to_timeframe
from .base import BrokerAPI, Candle

logger = logging.getLogger(__name__)


TIMEFRAME_TO_PERIOD = {
    "1m": model.ProtoOATrendbarPeriod.M1,
    "2m": model.ProtoOATrendbarPeriod.M2,
    "3m": model.ProtoOATrendbarPeriod.M3,
    "4m": model.ProtoOATrendbarPeriod.M4,
    "5m": model.ProtoOATrendbarPeriod.M5,
    "10m": model.ProtoOATrendbarPeriod.M10,
    "15m": model.ProtoOATrendbarPeriod.M15,
    "30m": model.ProtoOATrendbarPeriod.M30,
    "1h": model.ProtoOATrendbarPeriod.H1,
    "4h": model.ProtoOATrendbarPeriod.H4,
    "12h": model.ProtoOATrendbarPeriod.H12,
    "1d": model.ProtoOATrendbarPeriod.D1,
}


@dataclass
class SymbolInfo:
    symbol_id: int
    digits: int
    name: str


class CTraderConnection:
    """Minimal asyncio transport for the binary cTrader Open API protocol."""

    def __init__(self, host: str, port: int, use_tls: bool = True) -> None:
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._events: asyncio.Queue = asyncio.Queue()
        self._listen_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._last_send = time.monotonic()
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return bool(self._writer and not self._writer.is_closing())

    async def connect(self) -> None:
        if self.connected:
            return
        ssl_context = ssl.create_default_context() if self.use_tls else None
        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port, ssl=ssl_context
        )
        self._events = asyncio.Queue()
        self._pending.clear()
        self._closed = False
        self._listen_task = asyncio.create_task(self._read_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Connected to cTrader Open API at %s:%s", self.host, self.port)

    async def close(self) -> None:
        self._closed = True
        if self._listen_task:
            self._listen_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    async def request(self, message, timeout: float = 10.0):
        """Send a message and wait for the paired response by clientMsgId."""
        client_msg_id = os.urandom(8).hex()
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[client_msg_id] = future
        await self._send(message, client_msg_id=client_msg_id)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(client_msg_id, None)

    async def events(self):
        while True:
            payload = await self._events.get()
            if isinstance(payload, Exception):
                raise payload
            yield payload

    async def _send(self, message, client_msg_id: Optional[str] = None) -> None:
        if not self.connected:
            raise ConnectionError("Connection is not open")
        proto_message = common.ProtoMessage(
            payload=message.SerializeToString(),
            payloadType=message.payloadType,
            clientMsgId=client_msg_id or "",
        )
        data = proto_message.SerializeToString()
        packet = len(data).to_bytes(4, byteorder="big") + data
        async with self._lock:
            assert self._writer
            self._writer.write(packet)
            await self._writer.drain()
            self._last_send = time.monotonic()
            logger.debug("Sent message type %s", message.__class__.__name__)

    async def _send_heartbeat(self) -> None:
        try:
            await self._send(common.ProtoHeartbeatEvent())
        except Exception:
            logger.exception("Failed to send heartbeat")

    async def _heartbeat_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(5)
                if time.monotonic() - self._last_send > 20:
                    await self._send_heartbeat()
        except asyncio.CancelledError:
            return

    async def _read_loop(self) -> None:
        try:
            while not self._closed:
                assert self._reader
                header = await self._reader.readexactly(4)
                size = int.from_bytes(header, byteorder="big")
                data = await self._reader.readexactly(size)
                message = common.ProtoMessage()
                message.ParseFromString(data)

                if message.payloadType == common.ProtoHeartbeatEvent().payloadType:
                    logger.debug("Received heartbeat")
                    await self._send_heartbeat()
                    continue

                payload = Protobuf.extract(message)
                logger.debug("Received payload %s", payload.__class__.__name__)

                if message.clientMsgId and message.clientMsgId in self._pending:
                    future = self._pending.pop(message.clientMsgId)
                    if not future.done():
                        future.set_result(payload)
                else:
                    await self._events.put(payload)
        except asyncio.IncompleteReadError:
            logger.warning("Connection closed by peer")
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Read loop crashed")
        finally:
            self._closed = True
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Connection dropped"))
            self._pending.clear()
            try:
                self._events.put_nowait(ConnectionError("Connection dropped"))
            except Exception:
                pass
            if self._writer:
                self._writer.close()


class ICMarketsCTraderAPI(BrokerAPI):
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        use_tls: bool | None = None,
        default_symbol: str = os.getenv("DEFAULT_SYMBOL", "DE40"),
    ) -> None:
        self.client_id = os.getenv("CTRADER_CLIENT_ID")
        self.client_secret = os.getenv("CTRADER_CLIENT_SECRET")
        self.access_token = os.getenv("CTRADER_ACCESS_TOKEN")
        self.account_id = (
            int(os.getenv("CTRADER_ACCOUNT_ID"))
            if os.getenv("CTRADER_ACCOUNT_ID")
            else None
        )
        self.host = host or os.getenv("CTRADER_HOST", "demo.ctraderapi.com")
        self.port = port or int(os.getenv("CTRADER_PORT", "5035"))
        self.use_tls = (
            use_tls
            if use_tls is not None
            else os.getenv("CTRADER_USE_TLS", "true").lower() != "false"
        )
        self.default_symbol = default_symbol

        self._connection = CTraderConnection(self.host, self.port, self.use_tls)
        self._symbol_cache: Dict[str, SymbolInfo] = {}

    async def connect(self) -> None:
        if not self.client_id or not self.client_secret:
            raise ValueError("CTRADER_CLIENT_ID and CTRADER_CLIENT_SECRET must be set")
        if not self.access_token:
            raise ValueError("CTRADER_ACCESS_TOKEN must be set")

        await self._connection.connect()
        await self._version_handshake()
        await self._authenticate_application()
        await self._authenticate_account()
        logger.info("Authentication completed for cTrader account %s", self.account_id)

    async def _version_handshake(self) -> None:
        await self._connection.request(oa.ProtoOAVersionReq())

    async def _authenticate_application(self) -> None:
        req = oa.ProtoOAApplicationAuthReq(
            clientId=self.client_id,
            clientSecret=self.client_secret,
        )
        await self._connection.request(req)

    async def _authenticate_account(self) -> None:
        if self.account_id is None:
            lookup_req = oa.ProtoOAGetAccountListByAccessTokenReq(
                accessToken=self.access_token
            )
            lookup_res = await self._connection.request(lookup_req)
            accounts = list(lookup_res.ctidTraderAccount)
            if not accounts:
                raise RuntimeError("No cTrader accounts associated with this token")
            self.account_id = accounts[0].ctidTraderAccountId
            logger.info("Using CTID account %s from token lookup", self.account_id)

        account_req = oa.ProtoOAAccountAuthReq(
            ctidTraderAccountId=self.account_id,
            accessToken=self.access_token,
        )
        await self._connection.request(account_req)

    async def _resolve_symbol(self, symbol: str) -> SymbolInfo:
        symbol = symbol.upper()
        if symbol in self._symbol_cache:
            return self._symbol_cache[symbol]

        list_req = oa.ProtoOASymbolsListReq(
            ctidTraderAccountId=self.account_id, includeArchivedSymbols=False
        )
        list_res = await self._connection.request(list_req)
        symbol_id: Optional[int] = None
        for light in list_res.symbol:
            if light.symbolName.upper() == symbol:
                symbol_id = light.symbolId
                break
        if symbol_id is None:
            raise ValueError(f"Symbol {symbol} not found in account universe")

        by_id_req = oa.ProtoOASymbolByIdReq(
            ctidTraderAccountId=self.account_id, symbolId=[symbol_id]
        )
        by_id_res = await self._connection.request(by_id_req)
        if not by_id_res.symbol:
            raise RuntimeError(f"Unable to fetch full symbol info for {symbol}")
        full = by_id_res.symbol[0]
        self._symbol_cache[symbol] = SymbolInfo(
            symbol_id=symbol_id, digits=full.digits, name=symbol
        )
        return self._symbol_cache[symbol]

    def _trendbar_to_candle(
        self, trendbar: model.ProtoOATrendbar, symbol: str, timeframe: str, digits: int
    ) -> Candle:
        scale = 10**digits
        low = trendbar.low / scale
        open_price = (trendbar.low + trendbar.deltaOpen) / scale
        close_price = (trendbar.low + trendbar.deltaClose) / scale
        high_price = (trendbar.low + trendbar.deltaHigh) / scale
        open_time = datetime.fromtimestamp(
            trendbar.utcTimestampInMinutes * 60, tz=timezone.utc
        )
        period_minutes = TIMEFRAME_TO_MINUTES.get(timeframe)
        if period_minutes is None:
            raise ValueError(f"Unsupported timeframe {timeframe}")
        close_time = open_time + timedelta(minutes=period_minutes)
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            open=open_price,
            high=high_price,
            low=low,
            close=close_price,
            volume=float(trendbar.volume) if hasattr(trendbar, "volume") else None,
            open_time=open_time,
            close_time=close_time,
        )

    def _timeframe_period(self, timeframe: str):
        if timeframe not in TIMEFRAME_TO_PERIOD:
            raise ValueError(f"Timeframe {timeframe} is not supported natively")
        return TIMEFRAME_TO_PERIOD[timeframe]

    async def get_historical_candles(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> List[Candle]:
        await self.connect()
        info = await self._resolve_symbol(symbol)

        if timeframe not in TIMEFRAME_TO_PERIOD:
            raise ValueError(f"Timeframe {timeframe} is not supported for history")
        period = TIMEFRAME_TO_PERIOD[timeframe]
        period_minutes = TIMEFRAME_TO_MINUTES[timeframe]
        to_ts = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        from_ts = to_ts - int(period_minutes * limit * 60 * 1000)

        req = oa.ProtoOAGetTrendbarsReq(
            ctidTraderAccountId=self.account_id,
            fromTimestamp=from_ts,
            toTimestamp=to_ts,
            period=period,
            symbolId=info.symbol_id,
            count=limit,
        )
        res = await self._connection.request(req, timeout=15)
        candles = [
            self._trendbar_to_candle(tb, symbol, timeframe, info.digits)
            for tb in sorted(res.trendbar, key=lambda t: t.utcTimestampInMinutes)
        ]
        return candles

    async def stream_candles(
        self, symbol: str, timeframe: str
    ) -> AsyncIterator[Candle]:
        await self.connect()
        info = await self._resolve_symbol(symbol)

        if timeframe not in TIMEFRAME_TO_MINUTES:
            raise ValueError(f"Unsupported timeframe {timeframe}")
        target_timeframe = timeframe
        if timeframe in TIMEFRAME_TO_PERIOD:
            subscription_period = TIMEFRAME_TO_PERIOD[timeframe]
            base_timeframe = timeframe
        else:
            # Fallback to 1m data and aggregate upwards.
            subscription_period = TIMEFRAME_TO_PERIOD["1m"]
            base_timeframe = "1m"
        target_minutes = TIMEFRAME_TO_MINUTES[target_timeframe]

        sub_req = oa.ProtoOASubscribeLiveTrendbarReq(
            ctidTraderAccountId=self.account_id,
            period=subscription_period,
            symbolId=info.symbol_id,
        )
        last_open: Optional[datetime] = None
        last_emitted: Optional[datetime] = None
        raw_buffer: List[Candle] = []

        reconnect_delay = 1.0
        while True:
            try:
                await self._connection.request(sub_req)
                logger.info(
                    "Subscribed to live trendbars for %s (%s)",
                    symbol,
                    base_timeframe,
                )
                reconnect_delay = 1.0
                async for event in self._connection.events():
                    if isinstance(event, oa.ProtoOAErrorRes):
                        logger.error("Received error from server: %s", event)
                        continue

                    if isinstance(event, oa.ProtoOASpotEvent):
                        for tb in event.trendbar:
                            if tb.period != subscription_period:
                                continue
                            candle = self._trendbar_to_candle(
                                tb, symbol, base_timeframe, info.digits
                            )
                            if last_open is not None and candle.open_time <= last_open:
                                continue
                            last_open = candle.open_time
                            if target_timeframe == base_timeframe:
                                yield candle
                                last_emitted = candle.open_time
                            else:
                                raw_buffer.append(candle)
                                aggregated = aggregate_to_timeframe(
                                    raw_buffer, target_timeframe
                                )
                                for agg in aggregated:
                                    if last_emitted is None or agg.open_time > last_emitted:
                                        yield agg
                                        last_emitted = agg.open_time
                                if last_emitted:
                                    cutoff = last_emitted - timedelta(
                                        minutes=target_minutes
                                    )
                                    raw_buffer = [
                                        c for c in raw_buffer if c.open_time >= cutoff
                                    ]
            except ConnectionError:
                logger.warning(
                    "Stream connection lost, retrying in %.1fs", reconnect_delay
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30.0)
                await self.connect()
                continue
