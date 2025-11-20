from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from tabulate import tabulate

# Ensure local src/ is importable when running as a script.
ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT / "src"))

from broker_api.icmarkets_ctrader import ICMarketsCTraderAPI  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_historical(args) -> None:
    api = ICMarketsCTraderAPI()
    candles = await api.get_historical_candles(
        symbol=args.symbol, timeframe=args.timeframe, limit=args.limit
    )
    headers = ["open_time", "open", "high", "low", "close", "volume"]
    rows = [
        [
            c.open_time.isoformat(),
            f"{c.open:.5f}",
            f"{c.high:.5f}",
            f"{c.low:.5f}",
            f"{c.close:.5f}",
            f"{c.volume:.0f}" if c.volume is not None else "",
        ]
        for c in candles
    ]
    print(tabulate(rows, headers=headers))


async def run_stream(args) -> None:
    api = ICMarketsCTraderAPI()
    async for candle in api.stream_candles(symbol=args.symbol, timeframe=args.timeframe):
        volume_str = f"V:{candle.volume:.0f}" if candle.volume is not None else "V:0"
        line = (
            f"{candle.open_time.isoformat()} | "
            f"O:{candle.open:.5f} H:{candle.high:.5f} "
            f"L:{candle.low:.5f} C:{candle.close:.5f} "
            f"{volume_str}"
        )
        print(line)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="IC Markets cTrader Open API data layer demo"
    )
    parser.add_argument(
        "--symbol",
        default=os.getenv("DEFAULT_SYMBOL", "DE40"),
        help="Trading symbol (e.g. DE40/GER40)",
    )
    parser.add_argument(
        "--timeframe",
        default="3m",
        help="Timeframe (e.g. 3m, 1m, 5m, 1h)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    hist = subparsers.add_parser("historical", help="Fetch historical candles")
    hist.add_argument("--limit", type=int, default=100, help="Number of candles")

    subparsers.add_parser("stream", help="Stream live candles")
    return parser.parse_args()


async def main() -> None:
    load_dotenv()
    args = parse_args()
    if args.command == "historical":
        await run_historical(args)
    elif args.command == "stream":
        try:
            await run_stream(args)
        except KeyboardInterrupt:
            logger.info("Stopping stream...")


if __name__ == "__main__":
    asyncio.run(main())
