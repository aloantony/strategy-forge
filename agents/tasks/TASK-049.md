# TASK-049: Spec — Exposición de selección de fuente de datos en formulario de backtest

- **ID**: TASK-049
- **Priority**: P2
- **Status**: todo
- **Assigned**: Daniel
- **Blocked by**: —
- **Blocks**: TASK-050, TASK-051

## Files to read

- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-036-data-provider-spec.md` — spec de IHistoricalDataSource y symbols.json
- `src/data/interface.py` — contrato de IHistoricalDataSource
- `src/data/mt5_historical_source.py` — parámetros que requiere MT5HistoricalDataSource
- `src/data/dukascopy_historical_source.py` — parámetros que requiere DukascopyHistoricalDataSource
- `src/data/symbols.json` — registro canónico de símbolos y sus mappings
- `backtesting/runtime.py` — cómo recibe hoy data_source el BacktestEngine; qué parámetros pide el formulario actual
- `gui_charts.py` — sección del formulario de backtest (buscar `run_backtest` o `_on_backtest_run`); qué campos expone hoy al usuario

## Description

Daniel produce la spec de datos para exponer la selección de fuente de datos en el formulario de backtest. El objetivo es que el usuario pueda elegir entre MT5 y Dukascopy como fuente de datos históricos al lanzar un backtest desde la GUI, sin necesidad de modificar config.py. Daniel debe determinar: qué campos adicionales expone el formulario, cómo se instancia la fuente correcta a partir de la selección del usuario, y cómo se resuelve el símbolo canónico para cada fuente.

Daniel NO modifica código. Produce la spec que Alex y Grace/Felix usarán.

## Technical context

### Preguntas que la spec debe responder

1. **Selección de fuente**: ¿Dropdown con "MT5" y "Dukascopy"? ¿Checkbox "Usar Dukascopy"? Proponer la UI más simple.
2. **Parámetros condicionales**: MT5HistoricalDataSource requiere conexión activa con MT5. Si el usuario elige Dukascopy y MT5 no está conectado, ¿el backtest debe seguir funcionando? La respuesta debería ser sí — esa es la motivación de Dukascopy.
3. **Símbolo canónico**: El formulario de backtest hoy usa el símbolo activo de config (e.g. `#Germany40`). Dukascopy necesita el símbolo canónico (e.g. `GER40`) para resolver el ticker correcto de Dukascopy (`deuidxeur`). Daniel debe especificar la lógica de resolución: cómo mapear el símbolo del formulario al símbolo canónico que `DukascopyHistoricalDataSource` entiende.
4. **Instanciación**: ¿Quién instancia `MT5HistoricalDataSource` vs `DukascopyHistoricalDataSource`? Debe ser `gui_charts.py` (en el handler del backtest), no `backtesting/runtime.py`. Alex hará ese wiring en TASK-051.
5. **Parámetros de fecha/hora**: ¿Alguna fuente tiene restricciones de rango de fechas que el formulario deba comunicar al usuario?

### Archivos de referencia sobre el formulario actual

El formulario de backtest en la GUI tiene campos: símbolo, timeframe, fecha inicio, fecha fin, y lanza `BacktestEngine.run()`. El resultado se renderiza en el panel Backtest. Ver cómo `gui_charts.py` construye el payload al llamar al engine.

### Decisión pre-acordada: ubicación del factory

`build_data_source(...)` vive en **`src/data/factory.py`** — no en `backtesting/`. Razón: `src/data/` es la capa de abstracción de datos; `backtesting/` es un consumidor. Si en el futuro `main.py` u otro consumidor necesita instanciación dinámica, el factory ya está disponible. Daniel debe usar esta ubicación en su spec sin re-debatirla.

### Entregable

Un único archivo de spec: `agents/specs/TASK-049-datasource-selection-spec.md`

La spec debe incluir:
- Pseudocode de la lógica de resolución símbolo GUI → símbolo canónico → ticker Dukascopy
- Pseudocode del factory de data source: `build_data_source(source_name, symbol, ...) -> IHistoricalDataSource`
- Lista exacta de campos nuevos que el formulario GUI necesita exponer (con tipos y valores por defecto)
- Restricciones de compatibilidad entre fuente y parámetros de backtest

## Acceptance criteria

- [ ] Spec producida en `agents/specs/TASK-049-datasource-selection-spec.md`
- [ ] Spec define claramente qué campo(s) nuevo(s) se añaden al formulario de backtest
- [ ] Spec incluye pseudocode del factory `build_data_source(...)` que Grace/Felix y Alex pueden implementar verbatim
- [ ] Spec cubre la lógica de resolución símbolo del formulario → símbolo canónico → ticker de proveedor
- [ ] Spec cubre el caso en que el símbolo activo no tiene entry en symbols.json para Dukascopy (error claro al usuario)
- [ ] Spec indica quién instancia cada data source (gui_charts.py, no backtesting/runtime.py)
- [ ] Spec no modifica ningún archivo de código
