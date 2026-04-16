# TASK-035: Implementar MT5BrokerAdapter y refactorizar ExecutionEngine

- **ID**: TASK-035
- **Priority**: P1
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-034
- **Blocks**: TASK-038

## Files to read

- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-034-broker-adapter-interface.md` — la spec que debes implementar verbatim
- `trading.py` — módulo a envolver
- `src/runtime/execution_engine.py` — constructor y métodos que usan `self._trading`
- `main.py` — sitio de instanciación del engine (líneas ~60-150 aproximadamente; busca `ExecutionEngine(`)
- `config.py` — para verificar `PLAN_EXECUTOR_ENABLED` y `STRATEGY_RUNTIME_MODE`

## Description

Implementar la interfaz `IBrokerAdapter` y la clase concreta `MT5BrokerAdapter` según la spec de Daniel (TASK-034). Refactorizar `ExecutionEngine` para aceptar un `IBrokerAdapter` en lugar del módulo `trading` concreto. Actualizar `main.py` para instanciar `MT5BrokerAdapter` y pasarlo al engine.

## Technical context

- Archivos nuevos a crear: `src/broker/__init__.py`, `src/broker/interface.py`, `src/broker/mt5_adapter.py`
- Archivo a modificar: `src/runtime/execution_engine.py` — cambiar tipo de `trading_module` a `broker: IBrokerAdapter` en `__init__` y actualizar todas las llamadas internas
- Archivo a modificar: `main.py` — instanciar `MT5BrokerAdapter(trading)` y pasarlo donde antes se pasaba `trading`
- `trading.py` NO se modifica en esta tarea — `MT5BrokerAdapter` lo importa y delega
- La nueva carpeta `src/broker/` sigue el patrón de `src/runtime/` y `src/persistence/`
- Constraint crítico: `backtesting/runtime.py` NO se toca en esta tarea (tiene su propia abstracción en TASK-037)

## Acceptance criteria

- [ ] `src/broker/interface.py` existe con clase `IBrokerAdapter(ABC)` y todos los `@abstractmethod` de la spec
- [ ] `src/broker/mt5_adapter.py` existe con clase `MT5BrokerAdapter(IBrokerAdapter)` que delega a `trading.py`
- [ ] `src/runtime/execution_engine.py` acepta `broker: IBrokerAdapter` en lugar de `trading_module`; todas las llamadas a `self._trading.*` reemplazadas por llamadas al adaptador
- [ ] `main.py` instancia `MT5BrokerAdapter` y lo pasa al engine correctamente
- [ ] El bot arranca sin errores en modo `v1_only` (prueba manual o test de humo)
- [ ] Ningún test existente se rompe (`pytest tests/` pasa)
- [ ] `trading.py` permanece sin modificaciones (verificar con `git diff trading.py`)
