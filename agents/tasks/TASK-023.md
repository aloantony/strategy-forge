# TASK-023: Implementar piramidado en trading.py

- **ID**: TASK-023
- **Priority**: P1
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-020
- **Blocks**: TASK-025

## Files to read
- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-020-pyramiding-spec.md` — spec a implementar verbatim
- `trading.py` — funciones `apply_signal`, `get_position_info`, `_send_order`
- `main.py` — caller de `apply_signal`

## Description
Implementar los cambios en `trading.py` especificados por Daniel en TASK-020. Incluye: soporte para múltiples posiciones abiertas simultáneas bajo un mismo magic_number, lógica de detección de condición de piramidado, y la función o extensión de `apply_signal` que ejecuta entradas piramiadas con SL/TP absolutos.

## Technical context
- Seguir el spec de Daniel verbatim — sin decisiones de diseño propias
- `apply_signal()` existente no debe cambiar de comportamiento para estrategias sin piramidado (compatibilidad hacia atrás)
- `_send_order` actualmente calcula SL/TP como `precio ± sl_points × point`; si Daniel decide soporte para SL/TP absolutos, añadir parámetro opcional sin romper la firma existente
- Actualizar `main.py` si el spec lo requiere

## Acceptance criteria
- [ ] Todos los cambios del spec TASK-020 implementados en `trading.py`
- [ ] `apply_signal()` sin parámetros nuevos no cambia de comportamiento
- [ ] `get_position_info()` (o función nueva) devuelve todas las posiciones bajo un magic_number, ordenadas para identificar la más reciente
- [ ] Detección de condición de piramidado funciona correctamente para long-only
- [ ] Sin imports nuevos no justificados en `trading.py`
- [ ] `main.py` actualizado si el spec lo requiere
