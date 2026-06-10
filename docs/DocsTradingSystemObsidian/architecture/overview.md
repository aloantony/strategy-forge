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
  UI["Frontends\ngui_charts.py (desktop), futuros web/movil"]
  Server["Server Layer\nserver/ (FastAPI REST + WebSocket)"]
  App["Application Services\nbackend/application"]
  Entrypoints["Entrypoints\nbackend/main.py, backend/backtesting/cli.py"]
  Strategy["Strategy Layer\nstrategies/, backend/strategy/runtime.py"]
  Runtime["Runtime Layer\nbackend/runtime"]
  BrokerData["Broker/Data Layer\nbackend/brokers (mt5, paper), backend/data"]
  Persistence["Persistence Layer\nbackend/persistence, SQLite"]
  External["External Systems\nMT5 (opcional), Dukascopy, local files"]

  UI --> Server
  UI --> App
  Server --> App
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
| Frontends | Presentacion, eventos visuales, graficos y captura de intencion del usuario. | `frontend/web/` (cliente de referencia, servido por el server en `/`); `gui_charts.py` (desktop legacy, congelado — solo fixes criticos) |
| Server | API REST + WebSocket para conectar multiples frontends; broker-agnostico, Linux-ready. | `server/` (`uvicorn server.app:app`) |
| Application Services | Validacion y orquestacion reusable fuera de la GUI. | `backend/application/` |
| Entrypoints | Arranque de modos consola/CLI y loop live. | `backend/main.py`, `backend/backtesting/cli.py` |
| Strategy | Contrato comun y modulos de estrategia. | `backend/strategy/runtime.py`, `strategies/` |
| Runtime v1 | Decision estructurada, planes, ejecucion y estado. | `backend/runtime/` |
| Broker/Data | Adaptadores de broker (`IBrokerAdapter`: mt5/paper via factory) y fuentes de datos. | `backend/brokers/`, `backend/data/` |
| Persistence | SQLite, migraciones, repositorios y event log. | `backend/persistence/` |
| Agent Ops | Specs, reviews, tareas y roles. | `agents/` |

Regla dura: `backend/core`, `backend/application`, `backend/runtime` y `server/` no importan MT5
directamente; MT5 vive en `backend/brokers/mt5/` y `backend/data/mt5_*` como adaptador opcional
(`tests/test_backend_no_mt5.py` lo verifica). En Linux la app corre con el broker `paper`.

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
