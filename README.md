# IC Markets cTrader – Data Layer MVP

This module demonstrates a minimal but real connection to IC Markets via the official cTrader Open API. It focuses on streaming and fetching 3‑minute OHLC candles that can be plugged into later strategy/risk components.

## What is implemented
- Base `BrokerAPI` interface and `Candle` model (`broker_api/base.py`).
- Concrete IC Markets connector backed by the official Spotware Open API protobuf messages (`broker_api/icmarkets_ctrader.py`).
- Up-aggregation helper to build higher timeframes from lower ones (`broker_api/aggregation.py`).
- CLI demo with `historical` and `stream` commands (`main.py`).

## Credentials and configuration
Obtain client credentials and a trading account access token from the official cTrader Open API portal: https://help.ctrader.com/open-api/

Set the following environment variables (add them to a `.env` file for local runs):
- `CTRADER_CLIENT_ID`
- `CTRADER_CLIENT_SECRET`
- `CTRADER_ACCESS_TOKEN`
- `CTRADER_ACCOUNT_ID` (CTID numeric account id; if omitted the first account linked to the token is used)
- `CTRADER_HOST` (optional, defaults to `demo.ctraderapi.com`)
- `CTRADER_PORT` (optional, defaults to `5035`)
- `CTRADER_USE_TLS` (optional, defaults to `true`)
- `DEFAULT_SYMBOL` (optional, defaults to `DE40`)

## Quick start
Install dependencies:
```bash
pip install -r requirements.txt
```

Fetch historical candles:
```bash
python main.py historical --symbol DE40 --timeframe 3m --limit 100
```

Stream closed 3m candles in real time:
```bash
python main.py stream --symbol DE40 --timeframe 3m
```

## Notes
- Trendbar and authentication messages follow the official Spotware Open API protobuf definitions (bundled under `src/ctrader_open_api/messages`).
- If the broker does not provide the requested timeframe natively, the connector can subscribe to a lower timeframe (e.g., 1m) and aggregate upward using `aggregate_to_timeframe`.
