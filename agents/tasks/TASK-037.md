# TASK-037: Implementar MT5DataFeed, MT5HistoricalDataSource y desacoplar backtesting/runtime.py

- **ID**: TASK-037
- **Priority**: P1
- **Status**: done
- **Assigned**: Alex
- **Blocked by**: TASK-036, TASK-033
- **Blocks**: TASK-039

## Assignment note (Jarvis — 2026-04-13)

Esta tarea fue asignada originalmente a Felix por error. El scope cubre `backtesting/runtime.py`, `main.py`, `strategy_runtime.py` y la creación de `src/data/` — ninguno de estos archivos está dentro del scope de Felix (`gui_charts.py` exclusivamente). Reasignada a TBD pendiente de que el humano defina si se incorpora un nuevo agente backend coder o si la ejecuta él mismo directamente. Felix fue desbloqueado; la pregunta ha sido cerrada.

La misma situación aplica a TASK-041 (también reasignada a TBD).

## Files to read

- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-036-data-provider-spec.md` — la spec que debes implementar verbatim (el nombre correcto del archivo; ver sección "Scope de TASK-037" al final del documento)
- `data_feed.py` — funciones a envolver
- `backtesting/runtime.py` — función `_build_market_dataframe()` a refactorizar; imports de `mt5`, `config`, `data_feed` a eliminar
- `main.py` — uso actual de `data_feed.get_rates_df()`
- `config.py` — parámetros que hoy se leen directamente desde `backtesting/runtime.py`

## Description

Implementar las interfaces de datos según la spec de Daniel (TASK-036). Desacoplar `backtesting/runtime.py` de `mt5` directo y de `config` mediante inyección de `IHistoricalDataSource`. Desacoplar el runtime en vivo de `data_feed` directo mediante `IDataFeed`.

Esta tarea DEBE esperar a TASK-033 (sprint de Backtest GUI completo) porque `backtesting/runtime.py` fue modificado por TASK-031/032 durante ese sprint. Trabajar sobre el mismo archivo en paralelo causaría conflictos.

## Technical context

- Archivos nuevos a crear: `src/data/__init__.py`, `src/data/interface.py`, `src/data/mt5_data_feed.py`, `src/data/mt5_historical_source.py`
- Archivo a modificar: `backtesting/runtime.py` — reemplazar `_build_market_dataframe()` con inyección de `IHistoricalDataSource`; el constructor de `BacktestEngine` (si existe) o la función `run_backtest()` debe aceptar `data_source: IHistoricalDataSource`; eliminar imports directos de `mt5` y `config` donde ya no sean necesarios
- Archivo a modificar: `main.py` — instanciar `MT5DataFeed` y pasarlo al loop en lugar de llamar `data_feed.get_rates_df()` directamente
- `data_feed.py` NO se elimina todavía — `MT5DataFeed` y `MT5HistoricalDataSource` lo envuelven
- La GUI (`gui_charts.py`) también usa `data_feed` — el desacoplamiento de la GUI es TASK-039, NO esta tarea

## Acceptance criteria

- [ ] `src/data/interface.py` existe con `IDataFeed` e `IHistoricalDataSource`
- [ ] `src/data/mt5_data_feed.py` existe con `MT5DataFeed(IDataFeed)` implementado
- [ ] `src/data/mt5_historical_source.py` existe con `MT5HistoricalDataSource(IHistoricalDataSource)` implementado
- [ ] `backtesting/runtime.py` ya no importa `MetaTrader5 as mt5` directamente (lo hace `MT5HistoricalDataSource`)
- [ ] `backtesting/runtime.py` ya no lee `config.*` para parámetros de datos (los recibe vía la fuente inyectada)
- [ ] Los tests de backtesting existentes pasan (`pytest tests/test_backtest_runtime.py`)
- [ ] Se puede instanciar un `IHistoricalDataSource` mock en tests sin MT5 instalado
- [ ] `data_feed.py` permanece sin modificaciones (verificar con `git diff data_feed.py`)
