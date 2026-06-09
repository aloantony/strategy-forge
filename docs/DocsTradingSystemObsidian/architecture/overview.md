---
title: Architecture Overview
status: draft
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../../../main.py
  - ../../../gui_charts.py
  - ../../../strategy_runtime.py
  - ../../../backtesting/runtime.py
  - ../../../src/runtime/
  - ../../../src/broker/
  - ../../../src/data/
  - ../../../src/persistence/
---

# Architecture Overview

## Capas

```mermaid
flowchart TB
  UI["UI Layer\ngui_charts.py"]
  App["Application Services\nsrc/application"]
  Entrypoints["Entrypoints\nmain.py, backtesting/cli.py"]
  Strategy["Strategy Layer\nstrategies/, strategy_runtime.py"]
  Runtime["Runtime Layer\nsrc/runtime"]
  BrokerData["Broker/Data Layer\nsrc/broker, src/data, trading.py, data_feed.py"]
  Persistence["Persistence Layer\nsrc/persistence, SQLite"]
  External["External Systems\nMT5, Dukascopy, local files"]

  UI --> App
  Entrypoints --> App
  App --> Strategy
  App --> Runtime
  App --> BrokerData
  Entrypoints --> Strategy
  Entrypoints --> Runtime
  Runtime --> BrokerData
  Runtime --> Persistence
  BrokerData --> External
```

## Responsabilidades

| Capa | Responsabilidad | Archivos principales |
| --- | --- | --- |
| UI | Presentacion, eventos visuales, graficos y captura de intencion del usuario. | `gui_charts.py` |
| Application Services | Validacion y orquestacion reusable fuera de la GUI. | `src/application/` |
| Entrypoints | Arranque de modos consola/CLI y loop live. | `main.py`, `backtesting/cli.py` |
| Strategy | Contrato comun y modulos de estrategia. | `strategy_runtime.py`, `strategies/` |
| Runtime v1 | Decision estructurada, planes, ejecucion y estado. | `src/runtime/` |
| Broker/Data | Adaptadores a MT5, fuentes historicas y datos enriquecidos. | `src/broker/`, `src/data/`, `trading.py`, `data_feed.py` |
| Persistence | SQLite, migraciones, repositorios y event log. | `src/persistence/` |
| Agent Ops | Specs, reviews, tareas y roles. | `agents/` |

## Principios De Diseno

- Las estrategias deciden; no ejecutan ordenes.
- La GUI no debe ser duena de procesos de negocio.
- Los procesos reutilizables deben vivir en `src/application/` o en runtimes/backend existentes.
- `strategy_runtime.py` evita duplicar semantica entre live y backtest.
- `IBrokerAdapter` desacopla el motor v1 de MT5.
- `IHistoricalDataSource` desacopla backtesting de la fuente historica.
- `UnitOfWork` y repositorios concentran persistencia.
- Los agentes no deben tomar decisiones fuera de su rol.

## Flujos Principales

```mermaid
flowchart LR
  Strategy["Strategy module"] --> Payload["Signal payload"]
  Payload --> Live["Live runtime"]
  Payload --> Backtest["Backtest runtime"]
  Live --> Plan["Plan v1 or legacy signal"]
  Plan --> Broker["Broker adapter / trading.py"]
  Broker --> MT5["MT5"]
  Backtest --> Result["Backtest result"]
  Live --> DB["SQLite trace"]
```

## Deuda Arquitectonica Visible

- `gui_charts.py` todavia concentra demasiadas responsabilidades; se esta extrayendo por fases a `src/application/`.
- `trading.py` sigue siendo una capa legacy importante aunque `MT5BrokerAdapter` lo encapsula parcialmente.
- Algunas specs historicas en `agents/specs/` reflejan decisiones previas; antes de implementar se debe contrastar con codigo actual.
- La documentacion vieja y nueva deben convivir hasta que se haga una consolidacion explicita.
