# TASK-036: Diseño de IDataFeed e IHistoricalDataSource

- **ID**: TASK-036
- **Priority**: P1
- **Status**: done
- **Assigned**: Daniel
- **Blocked by**: TASK-034
- **Blocks**: TASK-037

## Files to read

- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-034-broker-adapter-interface.md` — leer para entender las convenciones de diseño establecidas
- `data_feed.py` — API actual: `get_rates_df()`, `add_source_columns()`, `add_baseline_bands()`, `add_supertrend()`, `add_tci()`
- `backtesting/runtime.py` — leer `_build_market_dataframe()` (~líneas 66-103): llama directamente a `mt5.copy_rates_range()`, `data_feed.*`, `config.*`. Este es el acoplamiento a abstraer.
- `main.py` — cómo llama `data_feed.get_rates_df()` en el loop de trading

## Description

Diseñar dos interfaces abstractas:
1. `IDataFeed` — fuente de datos de mercado para el runtime en vivo (reemplaza la llamada directa a `data_feed.get_rates_df()` + la cadena de `add_*`)
2. `IHistoricalDataSource` — fuente de datos históricos para el backtest engine (reemplaza la llamada directa a `mt5.copy_rates_range()` dentro de `_build_market_dataframe()`)

El resultado es una spec de diseño. Daniel NO implementa código.

## Technical context

- `IDataFeed` es para el runtime en vivo. Su responsabilidad: dado un símbolo y timeframe, retornar un `pd.DataFrame` ya enriquecido con todas las columnas derivadas (OHLC4, ATR bands, Supertrend, TCI). La implementación concreta `MT5DataFeed` envolverá `data_feed.get_rates_df()` + la cadena de `add_*`.
- `IHistoricalDataSource` es para el backtest engine. Su responsabilidad: dado un símbolo, timeframe, rango de fechas, retornar un `pd.DataFrame` crudo (OHLCV + columnas derivadas), análogo a lo que hace `_build_market_dataframe()` hoy. La implementación concreta `MT5HistoricalDataSource` envolverá `mt5.copy_rates_range()` + `data_feed.*`.
- La separación entre IDataFeed e IHistoricalDataSource es intencional: el runtime en vivo necesita "la última ventana de N velas", mientras el backtest necesita "todo el rango histórico con warmup". Son contratos diferentes.
- Ambas interfaces vivirán en `src/data/interface.py`. Las implementaciones MT5 en `src/data/mt5_data_feed.py` y `src/data/mt5_historical_source.py`.
- Considera si `add_source_columns`, `add_baseline_bands`, `add_supertrend`, `add_tci` son responsabilidad de la interfaz o del consumidor. Decisión recomendada: la implementación concreta aplica todas las transformaciones internamente; la interfaz contrata solo el DataFrame enriquecido.
- `config` no debe ser importado en las interfaces; los parámetros (MA_LENGTH, ATR_LENGTH, etc.) se pasan como argumentos al constructor de la implementación concreta.

## Acceptance criteria

- [ ] Spec producida en `agents/specs/TASK-036-data-interfaces.md`
- [ ] La spec define `IDataFeed` con su método principal: firma tipada, docstring, retorno documentado
- [ ] La spec define `IHistoricalDataSource` con su método principal: firma tipada, docstring, retorno documentado
- [ ] La spec documenta cómo `backtesting/runtime.py` recibirá la instancia de `IHistoricalDataSource` (constructor injection)
- [ ] La spec documenta cómo `main.py` y `gui_charts.py` recibirán `IDataFeed`
- [ ] La spec NO diseña cambios en `trading.py` ni en `IBrokerAdapter` — eso está en TASK-034
- [ ] La spec justifica explícitamente por qué son dos interfaces separadas y no una sola
