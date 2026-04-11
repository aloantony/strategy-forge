# TASK-034: Diseño de IBrokerAdapter — interfaz abstracta de broker

- **ID**: TASK-034
- **Priority**: P1
- **Status**: todo
- **Assigned**: Daniel
- **Blocked by**: —
- **Blocks**: TASK-035, TASK-036, TASK-038

## Files to read

- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto y decisiones estratégicas
- `trading.py` — API pública actual: `apply_signal()`, `_send_order()`, `_close_position()`, `calculate_dynamic_lot()`, `check_aggregate_risk()`, `get_open_positions()`, `get_account_info()`, `build_trade_comment()`
- `src/runtime/execution_engine.py` — consumidor actual; llama a `self._trading._send_order()` y `self._trading._close_position()` directamente

## Description

Diseñar la interfaz abstracta `IBrokerAdapter` que abstraerá toda interacción con el broker (órdenes, posiciones, datos de cuenta). El resultado es una spec de diseño — Daniel NO implementa código, produce pseudocode y la definición formal de la interfaz para que Felix la implemente en TASK-035.

Esta interfaz debe cubrir todas las operaciones que `trading.py` y `ExecutionEngine` necesitan hoy, sin añadir operaciones que no se usen todavía (YAGNI). El diseño debe también considerar cómo `ExecutionEngine` recibirá la implementación concreta (`MT5BrokerAdapter`) en lugar del módulo `trading` actual.

## Technical context

- Relevant files: `trading.py`, `src/runtime/execution_engine.py`
- Operaciones que `ExecutionEngine` usa directamente: `_send_order()`, `_close_position()` (accede a privados — esto es el problema a resolver)
- Operaciones que `main.py` usa: `apply_signal()`, `get_open_positions()`, `check_aggregate_risk()`, `calculate_dynamic_lot()`
- Operaciones que `gui_charts.py` usa: `get_open_positions()`, `get_account_info()`, `apply_signal()`
- La interfaz debe ser definible en un archivo nuevo `src/broker/interface.py` usando `abc.ABC` + `@abstractmethod`
- `MT5BrokerAdapter` vivirá en `src/broker/mt5_adapter.py` e implementará la interfaz envolviendo las funciones actuales de `trading.py`
- El `ExecutionEngine` debe recibir un `IBrokerAdapter` en su constructor en lugar de `trading_module`; el cambio de firma está acotado a `src/runtime/execution_engine.py`
- No se rompe `trading.py` — sigue existiendo; `MT5BrokerAdapter` lo envuelve

## Acceptance criteria

- [ ] Spec producida en `agents/specs/TASK-034-broker-adapter-interface.md`
- [ ] La spec define el protocolo completo de `IBrokerAdapter` como clase abstracta Python con `@abstractmethod`
- [ ] Cada método tiene: firma tipada, docstring breve, valor de retorno documentado
- [ ] La spec incluye la firma actualizada de `ExecutionEngine.__init__` (reemplazando `trading_module` por `broker: IBrokerAdapter`)
- [ ] La spec documenta la estrategia de compatibilidad: cómo `main.py` instancia `MT5BrokerAdapter` y lo pasa al engine
- [ ] La spec NO diseña la capa de datos (`IDataFeed`) — eso es TASK-036
- [ ] Daniel ha consultado las memorias de routing: si hay duda de si esto toca backtesting o GUI, escalate to Jarvis
