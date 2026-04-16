# TASK-052: Implementación GUI — Selector de fuente de datos en formulario de backtest

- **ID**: TASK-052
- **Priority**: P2
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-050, TASK-051
- **Blocks**: —

## Files to read

- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-050-datasource-gui-spec.md` — spec de Grace: cambios exactos en gui_charts.py (HTML, Python handler, threading)
- `agents/specs/TASK-049-datasource-selection-spec.md` — spec de Daniel: firma del factory y lógica de resolución
- `gui_charts.py` — archivo a modificar

## Description

Felix implementa en `gui_charts.py` los cambios especificados por Grace en TASK-050: añadir el selector de fuente de datos al formulario de backtest, leer el valor seleccionado en el handler Python, llamar al factory `build_data_source(...)` implementado por Alex (TASK-051), e inyectar el data source resultante en la llamada al BacktestEngine. Felix implementa la spec de Grace verbatim — no toma decisiones arquitectónicas.

## Technical context

### Resumen de cambios esperados (del flujo de la feature)

1. El formulario de backtest muestra un selector nuevo: "Fuente de datos" con opciones MT5 / Dukascopy
2. Cuando el usuario pulsa "Run backtest", el handler Python lee el valor del selector
3. El handler llama al factory `build_data_source(source_name, symbol)` (módulo implementado por Alex)
4. El data source resultante se inyecta en la llamada al engine (e.g. `BacktestEngine(data_source=ds, ...)`)
5. Si la fuente es Dukascopy y el símbolo no tiene mapping, el factory lanza `ValueError` — Felix debe capturarlo y mostrar feedback al usuario (toast o inline error, según lo que Grace especifique)

### Modo de operación

Felix opera en **spec-driven mode** para esta tarea. La spec de Grace (`TASK-050-datasource-gui-spec.md`) es la autoridad. Si la spec y el estado real de `gui_charts.py` difieren materialmente (landmark no existe, línea incorrecta), Felix escala a Jarvis antes de proceder.

### Patrones obligatorios

- Import del factory de Alex: `from src.data.factory import build_data_source` (o la ubicación que la spec indique)
- Manejo de errores de `ValueError` del factory: capturar y mostrar al usuario — no propagar silenciosamente
- Threading: respetar el modelo existente; si el backtest corre en hilo separado, la instanciación del factory debe ocurrir en ese mismo hilo
- No introducir nuevos imports de MT5 ni de Dukascopy directamente en `gui_charts.py` — solo importar el factory

## Acceptance criteria

- [ ] Selector de fuente de datos visible en el formulario de backtest con opciones MT5 y Dukascopy
- [ ] Valor por defecto: MT5 (comportamiento actual preservado)
- [ ] Handler Python lee el valor del selector y llama a `build_data_source(...)` con la firma correcta
- [ ] `build_data_source` result se pasa al BacktestEngine (inyección correcta según spec de Grace)
- [ ] `ValueError` del factory capturado y comunicado al usuario (no excepción silenciosa)
- [ ] Backtest con MT5 como fuente sigue funcionando exactamente igual que antes (cero regresiones)
- [ ] Backtest con Dukascopy funciona cuando MT5 no está conectado
- [ ] Solo se importa el factory en `gui_charts.py`, no `MT5HistoricalDataSource` ni `DukascopyHistoricalDataSource` directamente
- [ ] Threading correcto según spec de Grace
