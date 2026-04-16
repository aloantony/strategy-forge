# TASK-051: Wiring — Conectar fuente de datos seleccionada al BacktestEngine en gui_charts.py

- **ID**: TASK-051
- **Priority**: P2
- **Status**: done
- **Assigned**: Alex
- **Blocked by**: TASK-049
- **Blocks**: TASK-052

## Files to read

- `agents/alex.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-049-datasource-selection-spec.md` — spec de Daniel: factory pseudocode y lógica de resolución de símbolo
- `src/data/interface.py` — contrato de IHistoricalDataSource
- `src/data/mt5_historical_source.py` — implementación MT5
- `src/data/dukascopy_historical_source.py` — implementación Dukascopy
- `src/data/symbols.json` — registro canónico de símbolos
- `backtesting/runtime.py` — cómo recibe data_source el BacktestEngine actualmente

## Description

Alex implementa la función factory `build_data_source(source_name, symbol, ...) -> IHistoricalDataSource` según la spec de Daniel (TASK-049). Esta función vive en `backtesting/` o `src/data/` (Daniel decide en la spec la ubicación exacta). La función es el punto de inyección que `gui_charts.py` llamará antes de lanzar el backtest.

Alex no modifica `gui_charts.py` — ese es el scope de Felix (TASK-052 siguiendo la spec de Grace de TASK-050). Alex entrega solo la función factory y cualquier ajuste de imports necesarios en los módulos de backend.

## Technical context

### Función factory a implementar

Según el pseudocode de Daniel en `agents/specs/TASK-049-datasource-selection-spec.md`:

```
build_data_source(source_name: str, symbol: str, **kwargs) -> IHistoricalDataSource
```

- `source_name`: `"mt5"` o `"dukascopy"` (o los nombres que Daniel defina en la spec)
- `symbol`: símbolo tal como lo tiene la GUI (e.g. `"#Germany40"` o `"GER40"`) — la función resuelve el símbolo canónico internamente
- Devuelve una instancia de `IHistoricalDataSource` lista para inyectar en el engine
- Lanza `ValueError` con mensaje claro si `source_name` no es reconocido o si el símbolo no tiene mapping para la fuente solicitada

### Lógica de resolución de símbolo

La spec de Daniel define cómo mapear el símbolo del formulario GUI al símbolo canónico que `DukascopyHistoricalDataSource` entiende, leyendo `src/data/symbols.json`. Alex implementa esta lógica en la función factory.

### Ubicación del factory

Daniel define en TASK-049 dónde debe vivir esta función. Candidatos probables:
- `src/data/factory.py` — módulo nuevo en el paquete data
- `backtesting/data_sources.py` — módulo nuevo en el paquete backtesting

Alex debe seguir la ubicación que Daniel especifique. Si la spec no define ubicación explícita, escalar a Jarvis.

### Archivos que Alex NO toca

- `gui_charts.py` — Felix lo modifica siguiendo la spec de Grace (TASK-052)
- `backtesting/runtime.py` — no necesita cambios; ya acepta `data_source` inyectado
- `data_feed.py` — legacy wrapper; no modificar

## Acceptance criteria

- [ ] Función `build_data_source(source_name, symbol, **kwargs) -> IHistoricalDataSource` implementada en la ubicación que Daniel defina
- [ ] `build_data_source("mt5", symbol)` devuelve una instancia de `MT5HistoricalDataSource`
- [ ] `build_data_source("dukascopy", symbol)` devuelve una instancia de `DukascopyHistoricalDataSource` con el ticker resuelto desde `symbols.json`
- [ ] `build_data_source("dukascopy", symbol_sin_mapping)` lanza `ValueError` con mensaje claro
- [ ] `build_data_source("fuente_desconocida", ...)` lanza `ValueError` con mensaje claro
- [ ] La función es importable sin MT5 instalado (import condicional de mt5 si aplica)
- [ ] Tests en `tests/` verifican los tres casos de error + los dos casos válidos (mockeando las clases concretas)
- [ ] `gui_charts.py` no modificado (verificar con `git diff gui_charts.py`)
- [ ] `backtesting/runtime.py` no modificado (verificar con `git diff backtesting/runtime.py`)
