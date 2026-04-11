# TASK-038: Conectar ExecutionEngine a IBrokerAdapter en gui_charts.py

- **ID**: TASK-038
- **Priority**: P1
- **Status**: todo
- **Assigned**: Grace
- **Blocked by**: TASK-035
- **Blocks**: TASK-039

## Files to read

- `agents/grace.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-034-broker-adapter-interface.md` — interfaz ya implementada
- `gui_charts.py` — buscar todas las instanciaciones de `ExecutionEngine` y todos los accesos directos a `trading.*` en el contexto del bot loop (secciones: bot loop ~6206, `start_bot` ~6162, imports al inicio del archivo)
- `main.py` — ver el patrón correcto de instanciación `MT5BrokerAdapter` + `ExecutionEngine` que Felix estableció en TASK-035

## Description

La GUI (`gui_charts.py`) actualmente instancia `ExecutionEngine` pasando el módulo `trading` concreto. Tras TASK-035, el engine espera un `IBrokerAdapter`. Grace debe producir la spec de cambio para que Felix lo implemente de forma segura en `gui_charts.py`.

Esta es una tarea de spec (Grace), no de implementación. Felix implementará el cambio en TASK-039.

## Technical context

- `gui_charts.py` es el archivo de mayor riesgo del proyecto (~6374 líneas). Cualquier cambio requiere spec previa de Grace.
- El cambio es de alcance acotado: solo el punto de instanciación del `ExecutionEngine` y los imports correspondientes. No modifica ningún método de negocio de la GUI.
- La spec debe identificar: (1) la línea exacta donde se instancia `ExecutionEngine` en `gui_charts.py`, (2) los imports a añadir (`from src.broker.mt5_adapter import MT5BrokerAdapter`), (3) si `MT5BrokerAdapter` se instancia una vez en `__init__` o en `start_bot`, (4) el threading zone correcto para la instanciación.
- Si `gui_charts.py` llama a `trading.*` directamente en algún lugar fuera del `ExecutionEngine`, la spec debe documentarlo y decidir si se migra ahora o en una tarea posterior.
- Consulta la routing rule: cambios en bot loop / threading de `gui_charts.py` requieren spec de Grace antes de asignar a Felix.

## Acceptance criteria

- [ ] Spec producida en `agents/specs/TASK-038-gui-broker-adapter-integration.md`
- [ ] La spec identifica el número de línea exacto de cada instanciación de `ExecutionEngine` en `gui_charts.py`
- [ ] La spec lista todos los imports nuevos necesarios
- [ ] La spec especifica el threading zone correcto para cada cambio (main thread / bot-loop thread / callback thread)
- [ ] La spec documenta si hay llamadas directas a `trading.*` en `gui_charts.py` fuera del engine, y qué hacer con ellas
- [ ] La spec es autosuficiente: Felix puede implementar TASK-039 sin leer nada más que esta spec y el contexto estándar
