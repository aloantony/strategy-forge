# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a MetaTrader 5 (MT5) trading bot with a TradingView-style GUI. It runs multiple pluggable trading strategies concurrently and executes orders automatically.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot (main entry point)
python gui_charts.py

# Run bot without GUI (headless loop, for debugging)
python main.py
```

## Architecture

### Execution Flow

```
MT5 Connection
    ↓
main.py (Bot orchestrator)
    ├─ data_feed.py     → Fetches candles from MT5, preprocesses DataFrame
    ├─ strategies/      → Pluggable strategy modules (run in ThreadPoolExecutor)
    ├─ trading.py       → Order placement, position management
    └─ gui_charts.py    → TradingView-style interface (lightweight_charts)
```

### Key Files

- **config.py** — Central config: symbol, lot size, SL/TP points, active strategies, indicator params, thread settings
- **main.py** — Strategy loader (dynamic module resolution), main trading loop, magic number generation per strategy
- **trading.py** — Order execution; encodes trade metadata in comment strings (`"TAo|s=strategy|r=reason"`)
- **data_feed.py** — `get_rates_df()` fetches OHLCV, adds derived columns (OHLC4, HLC3, ATR bands, MAs)
- **backtest.py** — `BacktestEngine` class for historical simulation with P&L and drawdown metrics
- **strategies/builder.py** — Strategy `.py` file generator; called by the GUI's Strategy Builder to create/overwrite strategy modules from a JSON config
- **gui_charts.py** — 6613 line GUI; Strategy Builder UI, strategy enable/disable, Data Window for custom indicator values, performance metrics

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
