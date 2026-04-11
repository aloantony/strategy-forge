# TASK-039: Integrar supersistema v1 en gui_charts.py (STRATEGY_RUNTIME_MODE)

- **ID**: TASK-039
- **Priority**: P1
- **Status**: todo
- **Assigned**: Felix
- **Blocked by**: TASK-037, TASK-038
- **Blocks**: —

## Files to read

- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-038-gui-broker-adapter-integration.md` — spec de Grace; implementar verbatim
- `gui_charts.py` — archivo de destino; leer solo los rangos indicados en la spec de Grace
- `config.py` — verificar `STRATEGY_RUNTIME_MODE`, `PLAN_EXECUTOR_ENABLED`, `PERSISTENCE_ENABLED`
- `main.py` — referencia del patrón correcto de bootstrap v1 ya establecido allí

## Description

Implementar los cambios en `gui_charts.py` según la spec de Grace (TASK-038):
- Reemplazar la instanciación de `ExecutionEngine` con `trading_module` → `MT5BrokerAdapter`
- Añadir los imports necesarios
- Conectar la GUI al path v1 según `STRATEGY_RUNTIME_MODE` (leer con `getattr(config, "STRATEGY_RUNTIME_MODE", "legacy")`)
- Asegurar que `gui_charts.py` puede correr `backtesting/runtime.py` usando `MT5HistoricalDataSource` (integración de TASK-037)

Esta es la tarea que cierra el ciclo completo: después de TASK-039, el usuario puede arrancar `gui_charts.py` en modo `v1_only` y el runtime del bot en vivo + backtest usarán el supersistema v1 con abstracción de broker y datos.

## Technical context

- Tocar `gui_charts.py` con cambios de threading o imports del bot loop es de alta fragilidad — seguir la spec de Grace exactamente sin desviaciones
- El patrón correcto para leer config en `gui_charts.py`: `getattr(config, "STRATEGY_RUNTIME_MODE", "legacy")` (no `config.STRATEGY_RUNTIME_MODE` directamente)
- El modo `legacy` debe seguir funcionando sin cambios — el supersistema v1 es opt-in vía config
- Si la spec de Grace indica cambios en el threading zone del bot-loop, seguirlos sin simplificar: la estructura callback-queue existe por razones de seguridad de hilos

## Acceptance criteria

- [ ] `gui_charts.py` arranca sin errores en modo `legacy` (comportamiento sin cambios)
- [ ] `gui_charts.py` arranca sin errores en modo `v1_only` usando `MT5BrokerAdapter` e `MT5HistoricalDataSource`
- [ ] El tab Backtest funciona en modo `v1_only` usando `MT5HistoricalDataSource` inyectado
- [ ] No se rompe ninguna funcionalidad de la GUI existente (candles, strategy registry, side panel, Data Window)
- [ ] `pytest tests/` pasa sin regresiones
- [ ] El diff en `gui_charts.py` está acotado a los puntos indicados en la spec de Grace — no hay cambios en secciones no especificadas
