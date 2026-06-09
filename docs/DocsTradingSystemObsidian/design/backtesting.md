---
title: Backtesting Design
status: draft
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../../../src/application/backtest_service.py
  - ../../../backtesting/runtime.py
  - ../../../backtesting/cli.py
  - ../../../backtesting/FLUJO_BACKTESTING_ACTUAL.md
  - ../../../strategy_runtime.py
  - ../../../src/data/interface.py
---

# Backtesting Design

## Objetivo

Simular estrategias con la semantica mas cercana posible al runtime live sin tocar posiciones reales.

## Request

`BacktestService` prepara el request desde entradas GUI/CLI y `BacktestRequest.from_dict` normaliza el request final dentro del runtime:

- `strategy_key`, `strategy_label`, `module`.
- `symbol`.
- `timeframe_value`.
- `start_date`, `end_date`.
- `initial_balance`.
- `warmup_bars`.
- `lot`, `sl_points`, `tp_points`.
- `spread_points`, `slippage_points`, `commission_per_lot`.
- `data_provider`.

## DataFrame

`_build_market_dataframe`:

1. Resuelve label de timeframe.
2. Calcula `warmup_start`.
3. Llama `data_source.get_rates_df`.
4. Ordena por `time`.
5. Aplica `data_feed.add_source_columns`.

Luego `run_with_df` aplica procesamiento de estrategia con `strategy_runtime.apply_strategy_processing`.

## Loop De Simulacion

```mermaid
flowchart TD
  Start["strategy_df sorted"] --> Visible["Find visible indices"]
  Visible --> Initial{"Warmup before first visible?"}
  Initial -->|yes| Pending0["Compute initial pending_signal"]
  Initial -->|no| Loop["Loop visible candles"]
  Pending0 --> Loop
  Loop --> Apply["Apply pending signal at candle open"]
  Apply --> Exits["Process SL/TP exits"]
  Exits --> Equity["Mark equity"]
  Equity --> Next{"Has next visible candle?"}
  Next -->|yes| Signal["Compute signal on prefix for next candle"]
  Signal --> Loop
  Next -->|no| Close["Close open positions at END_OF_RANGE"]
  Close --> Result["Build success result"]
```

## Costes

El request soporta:

- Spread en puntos.
- Slippage en puntos.
- Comision por lote.

Estos costes afectan entrada y balance en la simulacion.

## Limitaciones

- No modela order book real.
- No modela rechazos de broker.
- El modo avanzado actual es long-only.
- Dynamic sizing avanzado se marca pero el lote real queda diferido por falta de metadata live completa en ese punto.

## Acceptance Basica Para Cambios

- Tests de `src/application/backtest_service.py` deben pasar si cambia validacion/request building.
- Tests existentes de `tests/test_backtest_runtime.py` deben pasar.
- Cambios de semantica deben actualizar [../architecture/backtesting.md](../architecture/backtesting.md).
- Si se modifica payload, revisar `strategy_runtime.py`, GUI y live loop.
