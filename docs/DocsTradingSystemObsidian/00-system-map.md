---
title: System Map
status: draft
audience: developers
last_reviewed: 2026-04-27
sources:
  - ../../README.md
  - ../../backend/core/config.py
  - ../../backend/main.py
  - ../../gui_charts.py
  - ../../backend/backtesting/runtime.py
  - ../../backend/runtime/
  - ../../backend/broker/
  - ../../backend/data/
  - ../../backend/persistence/
---

# System Map

Strategy Forge es un bot modular para MetaTrader 5 con GUI estilo TradingView, estrategias enchufables, backtesting y un runtime v1 con planes, persistencia y recursos canonicos.

## Vista General

```mermaid
flowchart LR
  Trader["Trader / Developer"] --> GUI["gui_charts.py\nTradingBotGUI"]
  GUI --> Services["backend/application\nApplication services"]
  Services --> Live["main.py\nLive bot loop"]
  Services --> BT["backend.backtesting.runtime\nBacktestEngine"]
  Live --> SR["backend/strategy/runtime.py\nStrategy helpers"]
  BT --> SR
  Live --> RuntimeV1["backend/runtime\nAdapter + Interpreter + Engine"]
  RuntimeV1 --> Broker["backend/broker\nIBrokerAdapter + MT5BrokerAdapter"]
  Broker --> MT5["MetaTrader 5"]
  Live --> Data["backend/data + data_feed.py\nMarket data"]
  BT --> Hist["IHistoricalDataSource\nMT5 / Dukascopy / File"]
  RuntimeV1 --> DB["SQLite\ntrading_bot.db"]
  Services --> Builder["strategy_builder/generator.py"]
  Builder --> Strategies["strategies/\n.py + .json"]
  SR --> Strategies
```

## Modulos De Alto Nivel

| Modulo | Responsabilidad |
| --- | --- |
| `gui_charts.py` | Interfaz visual, captura intencion del usuario, renderiza estado y delega procesos a servicios/runtimes. |
| `backend/application/` | Servicios reutilizables para procesos que no deben pertenecer a la GUI. |
| `backend/main.py` | Loop live sin GUI, carga de estrategias, analisis concurrente, runtime v1 y ejecucion legacy. |
| `backend/strategy/runtime.py` | Contrato comun para live, GUI y backtesting: timeframes, preparacion de DataFrame y normalizacion de senales. |
| `backend/brokers/mt5/trading.py` | Helpers legacy de MT5: mercado abierto, volumen, stops, ordenes, piramidado y riesgo agregado. |
| `backend/runtime/` | Supersistema v1: context builder, state store, adapter legacy, plan interpreter y execution engine. |
| `backend/brokers/` | Contrato `IBrokerAdapter` y adaptador concreto a MT5. |
| `backend/data/` | Contratos y fuentes de datos live/historicas: MT5, Dukascopy y file provider. |
| `backend/persistence/` | SQLite, migraciones y repositorios para planes, reports, legs, fills y event log. |
| `backend/backtesting/` | Motor de backtesting actual y CLI `python -m backend.backtesting runtime`. |
| `backend/strategy_builder/` | Generador de estrategias desde configuracion JSON. |
| `strategies/` | Estrategias Python independientes y configs generadas. |

## Rutas De Ejecucion

```mermaid
flowchart TD
  Start["Entrada"] --> Choice{"Modo"}
  Choice -->|GUI| GUI["python gui_charts.py"]
  Choice -->|Consola| Console["python -m backend.main"]
  Choice -->|Backtest CLI| CLI["python -m backend.backtesting runtime"]
  GUI --> Services["Application services"]
  Services --> GUIBT["BacktestService"]
  GUI --> GUIBot["Bot loop GUI"]
  GUIBT --> BT["backend.backtesting.run_backtest"]
  GUIBot --> LiveLike["TradingBotGUI.bot_loop"]
  Console --> MainLoop["backend.main.run_bot_loop"]
  CLI --> BT
  LiveLike --> Broker["MT5BrokerAdapter / trading.py"]
  MainLoop --> Runtime{"STRATEGY_RUNTIME_MODE"}
  Runtime -->|v1_only| V1["backend/runtime pipeline"]
  Runtime -->|legacy| Legacy["backend.brokers.mt5.trading.apply_signal"]
  V1 --> Broker
  Legacy --> Broker
```

## Fuentes De Verdad

- Config operativa: [config.py](../../backend/core/config.py).
- Contrato de estrategia: [strategies/README.md](../../strategies/README.md) y [backend/strategy/runtime.py](../../backend/strategy/runtime.py).
- Backtesting actual: [backtesting/FLUJO_BACKTESTING_ACTUAL.md](../../backend/backtesting/FLUJO_BACKTESTING_ACTUAL.md) y [backtesting/runtime.py](../../backend/backtesting/runtime.py).
- Persistencia: [backend/persistence/schema.py](../../backend/persistence/schema.py), [backend/persistence/dal.py](../../backend/persistence/dal.py).

## Como Pedir Correcciones

Si detectas una discrepancia entre esta documentacion y el codigo, abre un issue usando la plantilla de [templates/correction-request.md](templates/correction-request.md). Indica evidencia concreta: archivo, funcion, comportamiento observado y comportamiento esperado.
