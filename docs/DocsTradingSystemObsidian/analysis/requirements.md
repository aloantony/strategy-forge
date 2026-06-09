---
title: Requirements
status: draft
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../../../README.md
  - ../../../config.py
  - ../../../main.py
  - ../../../gui_charts.py
  - ../../../src/application/
  - ../../../strategy_runtime.py
  - ../../../backtesting/runtime.py
---

# Requirements

## Capacidades Funcionales

| Area | Requisito |
| --- | --- |
| GUI | Mostrar graficos, estrategias, indicadores, Data Window, backtest y controles del bot. |
| Application services | Centralizar validacion y orquestacion reutilizable iniciada desde GUI/CLI/tests. |
| Estrategias | Cargar modulos Python desde `strategies/` y soportar estrategias generadas por Builder. |
| Senales | Aceptar `buy`, `sell`, `none` desde `get_last_signal` o `get_last_signal_payload`. |
| Timeframes | Resolver `M1`, `M5`, `M15`, `M30`, `H1`, `H4`, `D1`. |
| Live loop | Analizar estrategias activas con concurrencia limitada y timeout. |
| Ejecucion | Enviar ordenes, cerrar posiciones, modificar SL/TP y aplicar piramidado cuando proceda. |
| Backtesting | Ejecutar una estrategia o comparacion de estrategias sobre historico. |
| Data sources | Usar MT5 y Dukascopy como fuentes historicas intercambiables. |
| Persistencia | Guardar estado, planes, reports, recursos canonicos y event log cuando v1 esta activo. |
| Agentes | Mantener tareas, specs y reviews con roles claros. |

## Requisitos No Funcionales

- **Trazabilidad**: runtime v1 debe persistir planes, reports y eventos.
- **Aislamiento**: las estrategias no deben importar GUI, broker ni config.
- **Compatibilidad**: estrategias legacy deben poder pasar por `LegacyStrategyAdapter`.
- **Resiliencia**: errores de estrategia o broker no deben tirar todo el loop.
- **Portabilidad documental**: los docs deben renderizar en Obsidian, GitHub y futura web HTML.
- **Minimo acoplamiento**: backtesting debe depender de `IHistoricalDataSource`, no de MT5 directamente cuando se inyecta una fuente.
- **GUI como entrada visual**: la GUI puede iniciar procesos, pero las reglas reutilizables deben vivir en `src/application/` o runtimes/backend existentes.

## Restricciones Actuales

- `config.SYMBOL` es el simbolo operativo principal en live.
- La ejecucion real depende de MT5 disponible y conectado.
- En Windows se usa `MetaTrader5`; fuera de Windows se contempla `mt5linux`.
- `gui_charts.py` es un archivo grande y sensible; cambios no triviales deben pasar por Grace/Felix.
- `STRATEGY_RUNTIME_MODE = "v1_only"` y `PLAN_EXECUTOR_ENABLED = True` hacen que el camino live principal use runtime v1 cuando la persistencia esta disponible.
- El backtesting no debe tocar posiciones reales.

## Contrato Minimo De Estrategia

```python
def get_last_signal(df, verbose=False) -> str:
    return "buy" | "sell" | "none"
```

Contrato recomendado:

```python
def get_last_signal_payload(df, verbose=False) -> dict:
    return {
        "signal": "buy",
        "reason": "texto corto",
    }
```

Funciones opcionales:

- `prepare_dataframe(df)`
- `compute_signals(df, enable_signals)`
- `compute_dir1_and_signals(df, enable_signals)`
- `TIMEFRAME`, `STRATEGY_TIMEFRAME` o `TIMEFRAME_STR`
- `PARAMS`
- `DATA_WINDOW_FIELDS`
- `MAGIC_NUMBER`
