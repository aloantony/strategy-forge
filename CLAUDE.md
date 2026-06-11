# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a trading bot with a TradingView-style GUI. It runs multiple pluggable trading strategies concurrently and executes orders automatically. The backend is broker-agnostic (`IBrokerAdapter`): MT5 is one optional adapter (Windows); a `paper` adapter allows running on Linux/servers without MT5. The GUI is a visual entrypoint, not the architectural owner of business processes; reusable process logic belongs in `backend/application/`, `backend/main.py`, `backend/backtesting/`, and `backend/runtime/`.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the desktop GUI (main entry point)
python gui_charts.py

# Run bot without GUI (headless loop, for debugging)
python -m backend.main

# Run current backtesting from the package
python -m backend.backtesting runtime --help

# Run the API server (REST + WebSocket; broker via TRADING_BROKER=mt5|paper|auto).
# Also serves the web frontend (frontend/web/) at http://<host>:8000/
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

## Documentation

Developer documentation lives in `docs/DocsTradingSystemObsidian/`. Keep it updated when architecture, agent routing, runtime behavior, or public contracts change.

Key docs:
- `docs/DocsTradingSystemObsidian/00-system-map.md`
- `docs/DocsTradingSystemObsidian/architecture/overview.md`
- `docs/DocsTradingSystemObsidian/architecture/application-services.md`
- `docs/DocsTradingSystemObsidian/design/gui.md`
- `docs/DocsTradingSystemObsidian/agents/routing-guide.md`

## Architecture

### Execution Flow

```
GUI / CLI / backend.main
    ↓
backend/application/   → process services shared by entrypoints
    ↓
runtime packages       → backend/backtesting/, backend/runtime/, backend/strategy/runtime.py
    ↓
adapters               → backend/brokers/ (mt5, paper), backend/data/
    ↓
external systems       → MT5 (optional), Dukascopy, SQLite/local files
```

Hard rule: `backend/core`, `backend/application`, `backend/runtime` and the (future) `server/` must not
import MT5 directly — only through `IBrokerAdapter`/`IHistoricalDataSource`. MT5 code lives in
`backend/brokers/mt5/` and `backend/data/mt5_*`, guarded by `backend/brokers/mt5_import.py` (mt5 is
`None` when unavailable). `tests/test_backend_no_mt5.py` enforces this.

### Key Files

- **backend/core/config.py** — Central config: symbol, lot size, SL/TP points, active strategies, indicator params, thread settings; `BROKER` selects the adapter (`mt5`/`paper`/auto)
- **backend/application/** — Application services shared by GUI/CLI/tests; `BacktestService` owns backtest request construction and datasource resolution
- **backend/main.py** — Headless live-trading loop (analysis scheduling, v1 plan cycle, order execution)
- **backend/strategy/loader.py** — Strategy discovery/loading (dynamic module resolution, PARAMS schema + `.params.json` overrides, magic number generation per strategy)
- **backend/brokers/** — `interface.py` (`IBrokerAdapter`), `factory.py` (selection), `paper.py` (in-memory broker), `mt5/` (adapter + legacy `trading.py`/`connection.py`)
- **backend/data/** — `IHistoricalDataSource` + sources (mt5, dukascopy, file) + `data_feed.py` (pure indicator/derived-column helpers; OHLCV fetch lives in `mt5_data_feed.py`)
- **backend/backtesting/** — backtesting package: `runtime.py` for the GUI/runtime-aligned engine and `python -m backend.backtesting runtime` for CLI entrypoints
- **backend/strategy_builder/generator.py** — Strategy `.py` file generator (v1 + MTF v2 routing); creates/overwrites strategy modules from a JSON config. Note: the emitted PARAMS block is declarative only — `.params.json` overrides don't affect Builder strategies
- **backend/application/builder_service.py** — Builder service for frontends: indicator catalog with human labels (`/api/builder/meta`), read/save/validate/delete of Builder strategies; used by `server/routers/builder.py` and the web wizard
- **gui_charts.py** — Large GUI file (desktop frontend, pending split into `frontend/desktop/`); Strategy Builder UI, strategy enable/disable, Data Window, performance metrics, and visual event handling

### Service Extraction Rule

Do not add new business process orchestration directly to `gui_charts.py`. Add it to `backend/application/` or an existing runtime/backend module, then call it from the GUI. GUI changes that remain visual still go through Grace/Felix; process/service changes go through Daniel/Alex when non-trivial.

### Strategy System

Strategies live in `strategies/` as independent Python modules. They must implement:

```python
def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    # Returns "buy", "sell", or "none"
    # Use df.iloc[-2] — the last *closed* candle
```

Optional but recommended:
- `get_last_signal_payload(df, verbose) -> dict` — `{"signal": "...", "reason": "..."}`
- `prepare_dataframe(df) -> pd.DataFrame` — adds custom indicator columns
- `compute_signals(df, enable_signals) -> pd.DataFrame` — adds `up_sig`/`dn_sig` columns for GUI markers
- `TIMEFRAME = "M1"` — strategy-specific timeframe (overrides global config)
- `DATA_WINDOW_FIELDS` — list of dicts defining what to show in the GUI Data Window
- `MAGIC_NUMBER` — optional int to override auto-generated magic number

Strategies are isolated: they must not import from `config`, `trading`, or `gui_charts`. They receive a prepared DataFrame and return signals only.

### Activating Strategies

In `config.py`:
```python
ACTIVE_STRATEGIES = ["my_strategy_name"]
```

Or dynamically via the GUI's "Estrategias" tab.

### Critical Config Settings

```python
SYMBOL = "#Germany40"   # DAX — prefix varies by broker
LOT = 0.01
SL_POINTS = 300
TP_POINTS = 500
SLEEP_SECONDS = 10      # Main loop interval
STRATEGY_MAX_WORKERS = 8
STRATEGY_ANALYSIS_TIMEOUT_SECONDS = 15
```

## Environment

The main bot uses MT5 directly (no `.env` needed for core trading).
