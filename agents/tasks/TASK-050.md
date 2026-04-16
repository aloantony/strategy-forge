# TASK-050: GUI spec — Selector de fuente de datos en formulario de backtest

- **ID**: TASK-050
- **Priority**: P2
- **Status**: done
- **Assigned**: Grace
- **Blocked by**: TASK-049
- **Blocks**: TASK-052

## Files to read

- `agents/grace.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-049-datasource-selection-spec.md` — spec de Daniel: qué campos nuevos y pseudocode del factory
- `gui_charts.py` — sección completa del formulario de backtest; localizar:
  - El HTML del formulario de backtest (campos actuales: símbolo, timeframe, fechas, botón Run)
  - El handler Python del evento "Run backtest" (`_on_backtest_run` o equivalente)
  - Cómo el handler construye y pasa parámetros a `BacktestEngine` o a la función de runtime
  - El threading zone del handler (¿llamada directa o vía callback-queue?)

## Description

Grace produce la spec de cambios en `gui_charts.py` para añadir el selector de fuente de datos al formulario de backtest. La spec debe ser suficientemente precisa para que Felix implemente sin ambigüedades. Grace NO modifica código.

## Technical context

### Entregable

Un único archivo de spec: `agents/specs/TASK-050-datasource-gui-spec.md`

### Secciones requeridas en la spec

**Sección 1 — Cambio HTML del formulario**

- El formulario de backtest actual tiene un conjunto de campos. Grace debe especificar exactamente dónde insertar el nuevo control (dropdown o radio) de selección de fuente.
- Especificar el HTML exacto del control: id, clase CSS, opciones ("MT5", "Dukascopy"), valor por defecto.
- Seguir el estilo visual existente del formulario (no introducir nueva paleta).

**Sección 2 — Cambio en el handler Python**

- Localizar el método Python que maneja el evento del botón "Run backtest".
- Especificar cómo ese método debe leer el valor del selector (via `event["data"]` o lectura de JS → Python).
- Especificar la llamada al factory `build_data_source(...)` definido por Daniel en TASK-049.
- El factory devuelve un `IHistoricalDataSource`; ese objeto se pasa a `BacktestEngine` (o equivalente). Grace debe especificar el punto de inyección exacto.

**Sección 3 — Threading**

- Confirmar si la llamada al backtest engine corre en hilo separado o en el callback thread.
- Si es hilo separado: especificar que `build_data_source` debe instanciarse en ese hilo (o antes de lanzarlo), no en el main thread.
- Confirmar que ninguna modificación a `chart.run_script()` es necesaria para esta feature (la selección de fuente es solo un parámetro de input; el resultado se renderiza igual que antes).

**Sección 4 — Insertion points**

Grace debe especificar con número de línea o landmark inequívoco:
- Dónde insertar el HTML del selector en el template del formulario
- Qué líneas del handler Python cambiar para leer el nuevo campo y construir la fuente

### Restricciones

- El formulario de backtest debe seguir funcionando con MT5 (comportamiento actual preservado como default)
- Dukascopy debe funcionar aunque MT5 no esté conectado
- Si el símbolo activo no tiene mapping para Dukascopy en `symbols.json`, el formulario debe mostrar un mensaje de error claro — especificar cómo (toast, inline error text, o disabled option)
- No introducir nuevas dependencias en `gui_charts.py` — el import de `DukascopyHistoricalDataSource` lo hace el handler a través del factory definido por Alex en TASK-051

## Acceptance criteria

- [ ] Spec producida en `agents/specs/TASK-050-datasource-gui-spec.md`
- [ ] HTML del selector especificado (id, clase, opciones, default)
- [ ] Punto de inserción HTML con landmark inequívoco o número de línea
- [ ] Cambio en el handler Python especificado línea por línea (qué se quita, qué se añade)
- [ ] Llamada al factory `build_data_source(...)` especificada con firma exacta según TASK-049
- [ ] Threading verificado y documentado
- [ ] Caso de error (símbolo sin mapping Dukascopy) especificado
- [ ] Spec no modifica ningún archivo de código
