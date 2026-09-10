---
title: Backtesting Architecture
status: draft
audience: developers
last_reviewed: 2026-04-27
sources:
  - ../../../backend/backtesting/FLUJO_BACKTESTING_ACTUAL.md
  - ../../../backend/application/backtest_service.py
  - ../../../backend/backtesting/runtime.py
  - ../../../backend/backtesting/cli.py
  - ../../../gui_charts.py
  - ../../../backend/strategy/runtime.py
---

# Backtesting Architecture

El motor activo es `backtesting.runtime`. La GUI lo usa a traves de `BacktestService`; la CLI actual puede llamarlo directamente.

## Flujo

```mermaid
sequenceDiagram
  autonumber
  participant GUI as GUI
  participant Service as BacktestService
  participant CLI as CLI
  participant Req as BacktestRequest
  participant DS as IHistoricalDataSource
  participant Engine as BacktestEngine
  participant SR as backend.strategy.runtime
  participant Strategy as Strategy Module

  GUI->>Service: prepare_run / prepare_comparison
  Service->>DS: build_data_source(source, symbol)
  Service->>Req: run_backtest(request, data_source)
  CLI->>Req: run_backtest(raw request)
  Req-->>Engine: normalized request
  Engine->>DS: get_rates_df(symbol, tf, warmup_start, end)
  DS-->>Engine: OHLCV DataFrame
  Engine->>SR: apply_strategy_processing(df, module)
  SR->>Strategy: prepare_dataframe / compute_signals
  Engine->>SR: get_strategy_signal_payload(prefix_df, module)
  SR->>Strategy: get_last_signal_payload / get_last_signal
  Engine-->>Service: metrics, trades, equity_curve, drawdown_curve
  Service-->>GUI: result dict
  Engine-->>CLI: metrics, trades, equity_curve, drawdown_curve
```

## Semantica Clave

- El backtest carga warmup antes del rango visible.
- La senal se calcula con prefijos crecientes del `DataFrame`.
- La senal se lee en vela cerrada.
- La entrada se ejecuta en el `open` de la siguiente vela visible.
- Si hay posicion abierta al final del rango, se cierra al ultimo `close` con `END_OF_RANGE`.
- Si una vela toca SL y TP, el motor prioriza SL de forma conservadora.

## Modos De Simulacion

| Modo | Activacion | Reglas |
| --- | --- | --- |
| Standard | `buy` o `sell` normal. | Una direccion activa; senal contraria cierra por `REVERSAL` y abre la nueva direccion. |
| Advanced buy | `signal == buy`, `pyramiding == True`, `atr_value > 0`. | Solo largos, permite piramidado si el precio avanza por umbral ATR. |
| Fallback | Payload avanzado incompleto. | Usa modo standard. |

## Resultado

`run_backtest` devuelve un dict con:

- `status`, `error`.
- Identidad: `strategy_key`, `strategy_label`, `symbol`, `digits`, `timeframe`, `data_provider`.
- Rango y balance: `start_date`, `end_date`, `initial_balance`, `final_balance`.
- Metricas: `total_profit`, `total_return_pct`, `closed_trades`, `win_rate`, `max_drawdown`, `profit_factor`, `expectancy`.
- Series: `trades`, `equity_curve`, `drawdown_curve`.
- Costes configurados: `spread_points`, `slippage_points`, `commission_per_lot`.

## Tests De Referencia

- [tests/test_backtest_runtime.py](../../../tests/test_backtest_runtime.py)
- [tests/test_backtesting_cli.py](../../../tests/test_backtesting_cli.py)
- [tests/test_backtest_service.py](../../../tests/test_backtest_service.py)
- [tests/test_dukascopy_historical_source.py](../../../tests/test_dukascopy_historical_source.py)
