---
title: Deployment Architecture
status: draft
audience: developers
last_reviewed: 2026-04-27
sources:
  - ../../../README.md
  - ../../../requirements.txt
  - ../../../backend/core/config.py
  - ../../../backend/mt5_import.py
---

# Deployment Architecture

## Entorno Principal

```mermaid
flowchart TB
  subgraph Windows["Windows workstation"]
    Python["Python process\nStrategy Forge"]
    MT5["MetaTrader 5 terminal\nlogged in"]
    DB["SQLite file\ntrading_bot.db"]
    Files["Repo files\nstrategies, docs, agents"]
  end

  Python -->|MetaTrader5 package| MT5
  Python --> DB
  Python --> Files
  Python -->|optional historical API| Dukascopy["Dukascopy"]
```

## Dependencias

Desde [requirements.txt](../../../requirements.txt):

- `MetaTrader5` en Windows.
- `mt5linux` fuera de Windows.
- `pandas`.
- `matplotlib`.
- `customtkinter`.
- `lightweight-charts`.
- `dukascopy-python>=4.0.1`.

## Entrypoints

| Comando | Uso |
| --- | --- |
| `python gui_charts.py` | Modo principal con GUI. |
| `python -m backend.main` | Loop live sin GUI, util para debugging. |
| `python -m backend.backtesting runtime --help` | CLI de backtesting actual. |

## Mac/Linux

`backend/core/config.py` contiene `MT5LINUX_HOST` y `MT5LINUX_PORT`. En plataformas no Windows, el sistema depende de un servidor `mt5linux` conectado a una maquina Windows con MT5.

## Datos Locales

- Estrategias: `strategies/`.
- Config generada por Strategy Builder: `strategies/*.json`.
- Base SQLite: `trading_bot.db` por defecto.
- Documentacion operativa: `docs/`.

## Consideraciones

- MT5 debe estar abierto y con cuenta conectada antes de arrancar.
- El simbolo debe existir y estar visible en Market Watch.
- El prefijo del simbolo depende del broker.
- Para publicar docs HTML no hace falta cambiar runtime; solo anadir toolchain documental.

