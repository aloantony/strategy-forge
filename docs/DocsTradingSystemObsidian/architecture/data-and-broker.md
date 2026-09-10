---
title: Data And Broker Architecture
status: draft
audience: developers
last_reviewed: 2026-04-27
sources:
  - ../../../backend/data/data_feed.py
  - ../../../backend/brokers/mt5/trading.py
  - ../../../backend/application/backtest_service.py
  - ../../../backend/data/interface.py
  - ../../../backend/data/factory.py
  - ../../../backend/data/mt5_data_feed.py
  - ../../../backend/data/mt5_historical_source.py
  - ../../../backend/data/dukascopy_historical_source.py
  - ../../../backend/broker/interface.py
  - ../../../backend/broker/mt5_adapter.py
---

# Data And Broker Architecture

## Interfaces

```mermaid
classDiagram
  class IDataFeed {
    <<interface>>
    +get_enriched_df(symbol, timeframe, bars) DataFrame
  }

  class IHistoricalDataSource {
    <<interface>>
    +get_rates_df(symbol, timeframe, start, end) DataFrame
    +get_instrument_info(symbol) InstrumentInfo
  }

  class IBrokerAdapter {
    <<interface>>
    +send_order(...)
    +close_position(...)
    +modify_sl(...)
    +modify_tp(...)
    +apply_signal(...)
    +apply_pyramid_signal(...)
    +is_market_open(symbol)
    +get_open_positions(symbol, magic)
    +get_account_info()
    +get_instrument_info(symbol)
  }

  class MT5DataFeed
  class MT5HistoricalDataSource
  class DukascopyHistoricalDataSource
  class FileProvider
  class MT5BrokerAdapter

  IDataFeed <|.. MT5DataFeed
  IHistoricalDataSource <|.. MT5HistoricalDataSource
  IHistoricalDataSource <|.. DukascopyHistoricalDataSource
  IHistoricalDataSource <|.. FileProvider
  IBrokerAdapter <|.. MT5BrokerAdapter
```

## Datos Live

`IDataFeed.get_enriched_df` retorna un `DataFrame` listo para estrategia:

- `time`, `open`, `high`, `low`, `close`, `tick_volume`.
- Columnas fuente: `OHLC4`, `HLC3`, `HL2`, `CLOSE`.
- Baseline bands: `average`, `upper`, `lower`, `atr`.
- Supertrend: `supertrend`, `supertrend_dir`, `supertrend_up`, `supertrend_down`.
- TCI: `tci`, `tci_signal`, `tci_hist`.

`backend/main.py` usa `MT5DataFeed` por defecto. `backend/data/data_feed.py` conserva helpers legacy para enriquecer datos y es reutilizado por backtesting.

## Datos Historicos

```mermaid
flowchart LR
  GUI["GUI request"] --> Service["BacktestService"]
  Service --> Factory["build_data_source(source, symbol)"]
  CLI["CLI request"] --> Factory
  Factory -->|mt5| MT5Source["MT5HistoricalDataSource"]
  Factory -->|dukascopy| DukaSource["DukascopyHistoricalDataSource"]
  Factory --> Symbols["symbols.json\ncanonical mapping"]
  MT5Source --> Backtest["BacktestEngine"]
  DukaSource --> Backtest
```

La factoria:

- No importa `config`.
- Para MT5 devuelve `MT5HistoricalDataSource`.
- Para Dukascopy resuelve simbolo canonico con `symbols.json`.
- Falla temprano si falta `dukascopy-python` o mapping del simbolo.

## Broker

`MT5BrokerAdapter` implementa `IBrokerAdapter` usando `backend/brokers/mt5/trading.py` para:

- Normalizar volumen.
- Ajustar SL/TP a reglas del simbolo.
- Elegir filling mode.
- Reintentar order send con filling compatible.
- Aplicar senales legacy cuando el runtime no usa plan executor.

El adapter es la frontera entre runtime v1 y MT5. Nuevos brokers deben implementar `IBrokerAdapter` sin cambiar `ExecutionEngine`.

## Riesgos

- `backend/brokers/mt5/trading.py` sigue concentrando logica legacy y debe tratarse como modulo compartido sensible.
- `mt5` puede ser `None` si la dependencia no esta disponible.
- Las reglas de simbolo dependen del broker: point, tick size, tick value, volume step, stops level y filling mode.
