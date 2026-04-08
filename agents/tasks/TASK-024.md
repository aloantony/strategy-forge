# TASK-024: Implementar sizing dinámico y control de riesgo en trading.py

- **ID**: TASK-024
- **Priority**: P1
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-021
- **Blocks**: TASK-025

## Files to read
- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-021-dynamic-sizing-risk-spec.md` — spec a implementar verbatim
- `trading.py` — `_send_order`, `apply_signal`, `normalize_volume`
- `config.py` — `LOT`

## Description
Implementar el cálculo de lot dinámico y la verificación de riesgo agregado según el spec de Daniel (TASK-021). La función de sizing debe ser invocable tanto para la entrada inicial como para cada entrada piramiada. `config.LOT` sigue siendo el fallback para estrategias sin sizing dinámico.

## Technical context
- `mt5.account_info().balance` — base del cálculo (decisión cerrada: balance, no equity)
- `mt5.symbol_info(symbol)` da `contract_size`, `tick_value`, `tick_size`, `point` — necesarios para convertir riesgo en dinero a lotes
- El lot calculado debe pasar por `normalize_volume()` antes de enviarse
- El sizing dinámico se activa solo si la estrategia lo solicita via payload — estrategias sin sizing siguen usando `config.LOT`

## Acceptance criteria
- [ ] Función de cálculo de lot dinámico implementada según spec TASK-021
- [ ] Verificación de riesgo agregado implementada (suma riesgo posiciones actuales + nueva entrada vs. 3% balance)
- [ ] Si el riesgo agreado superaría el 3%, la entrada se rechaza y se registra el motivo
- [ ] Estrategias sin sizing dinámico siguen usando `config.LOT` sin cambios
- [ ] El lot calculado pasa siempre por `normalize_volume()` antes de enviarse
