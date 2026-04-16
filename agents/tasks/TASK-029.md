# TASK-029: Spec backend — comparación multi-estrategia en el motor de backtest

- **ID**: TASK-029
- **Priority**: P2
- **Status**: done
- **Assigned**: Daniel
- **Blocked by**: nada
- **Blocks**: TASK-030

## Files to read
- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `backtesting/runtime.py` — entender `run_backtest`, `BacktestRequest`, `BacktestEngine._build_success_result`
- `gui_charts.py` líneas 821–924 — `_run_backtest_worker` y `_on_backtest_run`: ver cómo el request llega desde la GUI y cómo se dispara el thread

## Description

La feature de comparación de estrategias requiere ejecutar N backtests (una por estrategia) con el mismo símbolo y rango de fechas, y retornar un resultado comparativo unificado. Daniel debe diseñar el mecanismo backend: una función nueva o una extensión de la interfaz existente que la GUI pueda llamar de la misma forma que llama a `run_backtest` hoy.

## Technical context

- Relevant files: `backtesting/runtime.py`, `gui_charts.py`
- Relevant functions: `run_backtest(request: dict) -> dict`, `BacktestRequest.from_dict`, `BacktestEngine.run`
- La GUI actualmente llama `run_backtest(request)` en un thread background. El nuevo mecanismo debe ser compatible con el mismo patrón de thread.
- Cada ejecución individual es costosa (descarga de datos MT5 + iteración por velas). La spec debe decidir si los N runs comparten el DataFrame base (descargar una vez, reusar) o si cada uno descarga independientemente.
- El resultado de comparación debe ser JSON-serializable (sin datetime, sin objetos MT5).
- La GUI necesitará una forma de identificar qué estrategias comparar — la spec debe definir el shape del request de comparación.

## What Daniel must produce

Un spec en `agents/specs/TASK-029-backtest-comparison-backend-spec.md` que incluya:

1. **Firma de la función nueva** (o extensión de `run_backtest`) que la GUI llamará, con tipos de entrada y salida.
2. **Shape del request de comparación**: qué campos tiene el dict que la GUI enviará.
3. **Shape del resultado de comparación**: qué campos retorna — tabla resumen por estrategia (con las mismas métricas que el resultado individual) y posiblemente un campo `strategies` con los resultados individuales completos.
4. **Decisión sobre compartir DataFrame base**: si el DataFrame de mercado se descarga una vez y se comparte entre engines, o cada uno descarga por separado. Justificación con pros/contras.
5. **Pseudocode** de la función/extensión nueva.
6. **Manejo de errores**: si una estrategia falla, ¿cancela todo o retorna resultado parcial?

## Acceptance criteria
- [ ] Spec existe en `agents/specs/TASK-029-backtest-comparison-backend-spec.md`
- [ ] Spec define la firma completa de la función de comparación
- [ ] Spec define el shape del request (campos obligatorios y opcionales)
- [ ] Spec define el shape del resultado: array de estrategias con métricas homogéneas
- [ ] Spec toma decisión explícita sobre DataFrame compartido vs. descarga independiente
- [ ] Spec define comportamiento en caso de error parcial (fallo de una estrategia)
- [ ] Pseudocode es suficientemente detallado para implementación sin decisiones adicionales
