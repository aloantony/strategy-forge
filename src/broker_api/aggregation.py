from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from .base import Candle

# Minutes per timeframe string used across the module.
TIMEFRAME_TO_MINUTES = {
    "1m": 1,
    "2m": 2,
    "3m": 3,
    "4m": 4,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "12h": 720,
    "1d": 1440,
}


def _bucket_start(timestamp: datetime, bucket_minutes: int) -> datetime:
    unix_minutes = int(timestamp.timestamp() // 60)
    base_minutes = unix_minutes - (unix_minutes % bucket_minutes)
    return datetime.fromtimestamp(base_minutes * 60, tz=timestamp.tzinfo or timezone.utc)


def aggregate_to_timeframe(
    raw_candles: Iterable[Candle],
    target_timeframe: str,
) -> List[Candle]:
    """
    Aggregate a stream or list of smaller candles (e.g. 1m) into a higher timeframe (e.g. 3m).

    Supported up-aggregation mappings include:
    - 1m -> 3m
    - 1m -> 5m
    Additional combinations where the target is an integer multiple of the source
    timeframe will also work.
    """
    candles = sorted(raw_candles, key=lambda c: c.open_time)
    if not candles:
        return []

    if target_timeframe not in TIMEFRAME_TO_MINUTES:
        raise ValueError(f"Unsupported target timeframe: {target_timeframe}")

    source_timeframe = candles[0].timeframe
    if source_timeframe not in TIMEFRAME_TO_MINUTES:
        raise ValueError(f"Unsupported source timeframe: {source_timeframe}")

    target_minutes = TIMEFRAME_TO_MINUTES[target_timeframe]
    source_minutes = TIMEFRAME_TO_MINUTES[source_timeframe]
    if target_minutes % source_minutes != 0:
        raise ValueError(
            f"Cannot aggregate {source_timeframe} into {target_timeframe}: "
            "target is not a multiple of source"
        )

    buckets: dict[datetime, Candle] = {}
    for candle in candles:
        start = _bucket_start(candle.open_time, target_minutes)
        close_time = start + timedelta(minutes=target_minutes)
        if start not in buckets:
            buckets[start] = Candle(
                symbol=candle.symbol,
                timeframe=target_timeframe,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                open_time=start,
                close_time=close_time,
            )
            continue

        bucket = buckets[start]
        bucket.high = max(bucket.high, candle.high)
        bucket.low = min(bucket.low, candle.low)
        bucket.close = candle.close
        if bucket.volume is None or candle.volume is None:
            bucket.volume = None
        else:
            bucket.volume += candle.volume

    return [buckets[key] for key in sorted(buckets.keys())]

