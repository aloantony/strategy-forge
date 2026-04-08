# TASK-026: Implementar cambios GUI para piramidado (condicional)

- **ID**: TASK-026
- **Priority**: P1
- **Status**: done
- **Assigned**: Felix
- **Blocked by**: TASK-022
- **Blocks**: nada

## Files to read
- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-022-pyramiding-gui-spec.md` — spec a implementar verbatim
- `gui_charts.py` — solo los puntos de inserción listados en el spec de Grace

## Description
Implementar los cambios en `gui_charts.py` especificados por Grace en TASK-022. Esta tarea solo procede si Grace determina que son necesarios cambios. Si el spec de Grace concluye "no-op", esta tarea se cierra como done sin cambios.

## Technical context
- Seguir el spec de Grace verbatim — sin decisiones de diseño propias
- `gui_charts.py` es el archivo de mayor riesgo del proyecto — todos los cambios deben ser quirúrgicos y sin refactoring oportunista

## Acceptance criteria
- [ ] Si spec TASK-022 es "no-op": tarea cerrada como done, sin cambios en `gui_charts.py`
- [ ] Si spec TASK-022 requiere cambios: todos los puntos de inserción del spec implementados
- [ ] No se rompe ninguna funcionalidad existente (chart, tab estrategias, Data Window, métricas)
- [ ] GUI lanza sin errores
