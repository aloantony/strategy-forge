# Adopcion Incremental En El Codebase Actual v1

## Objetivo

Bajar la propuesta del supersistema al repo real sin hacer un big bang rewrite.

La migracion correcta no es:
- romper `main.py`
- romper `trading.py`
- reescribir la GUI primero
- obligar a convertir todas las estrategias de golpe

La migracion correcta si es:
- introducir capas nuevas al lado del camino legacy
- instrumentar primero antes de sustituir
- mantener compatibilidad temporal con estrategias actuales
- mover la fuente de verdad hacia `plan`, `state` y `event_log`
- retirar lo viejo solo cuando el camino nuevo ya sea estable

## Puntos de acoplamiento reales hoy

### `main.py`

Hoy concentra casi todo el runtime estrategico:
- descubre y carga estrategias con `load_active_strategies()`
- resuelve `magic_number` por estrategia
- construye `DataFrame` de mercado por timeframe
- llama a `_apply_strategy_processing()`
- llama a `_analyze_strategy()`
- consume `get_last_signal()` o `get_last_signal_payload()`
- serializa la ejecucion con `ORDER_EXECUTION_LOCK`
- termina llamando a `trading.apply_signal()`

Conclusion:
- `main.py` es hoy cargador, scheduler, context builder parcial y orquestador de ejecucion a la vez

### `trading.py`

Hoy contiene dos capas mezcladas:

1. Infraestructura MT5 legitima:
- `order_send_with_filling_retry()`
- normalizacion de volumen
- ajuste tecnico de stops
- helpers de ordenes y cierre

2. Politica de ejecucion legacy:
- `get_open_position_direction()`
- `get_position_info()`
- `_close_position()`
- `_send_order()`
- `apply_signal()`

`apply_signal()` es el cuello de botella actual porque traduce:
- `buy`
- `sell`
- `none`

a una unica logica de:
- abrir si no hay nada
- cerrar y girar si hay posicion opuesta
- no hacer nada si ya vas en la misma direccion

Eso es demasiado estrecho para `legs`, `entry_groups`, parciales o pyramiding.

### `gui_charts.py`

Hoy mantiene un sistema paralelo al runtime:
- registro propio de estrategias
- carga y resolucion propias
- seleccion visual por estrategia
- builder UI propio
- guardado del builder llamando directo a `generate_strategy_file()`

Problema:
- la GUI hoy no es solo presentacion
- tambien actua como segunda fuente de verdad de estrategias

### `strategies/builder.py`

Hoy genera estrategias del modelo legacy:
- preparan `DataFrame`
- calculan columnas
- emiten `buy/sell/none`

Es util para el sistema actual, pero no genera estrategias con:
- `state`
- `plan`
- `actions`
- targeting por `leg`
- gestion avanzada de posicion

## Restricciones de migracion acordadas

1. No romper estrategias legacy existentes.
2. No bloquear el bot mientras se construye la arquitectura nueva.
3. No mover la GUI primero.
4. No meter acceso directo a SQLite o MT5 dentro de las estrategias.
5. No mezclar "observabilidad" con "cambio de comportamiento" en el mismo paso.
6. Mantener capacidad de rollback por feature flag.

## Estrategia general de adopcion

La adopcion debe seguir este principio:

`primero observar -> luego envolver -> luego sustituir -> por ultimo retirar`

Eso evita dos errores clasicos:
- reescribir demasiado antes de tener trazabilidad
- cambiar ejecucion sin tener persistencia ni replay

## Modo dual temporal

Durante la transicion deben convivir dos contratos.

### Contrato legacy

Compatible con lo que ya existe:
- `prepare_dataframe(df)`
- `compute_signals(df)` o equivalentes
- `get_last_signal(df)` o `get_last_signal_payload(df)`

Salida real:
- `buy`
- `sell`
- `none`

### Contrato v1

Nuevo contrato objetivo:
- `decide(context, state) -> decision`

Donde `decision` contiene al menos:
- `plan`
- `next_state`

Y donde `plan` contiene:
- `plan_id`
- `schema_version`
- `actions`
- `reason`

### Adaptador de compatibilidad

Debe existir una capa puente que permita tratar una estrategia legacy como una
estrategia v1.

Funcion del adaptador:
- construir un `plan` sintetico a partir de `buy/sell/none`
- mantener el mismo comportamiento observable mientras el ejecutor nuevo no sea
  la ruta principal
- registrar la decision bajo el nuevo sistema de persistencia

Regla importante:
- una estrategia legacy no debe saber que esta siendo adaptada

## Fases de adopcion

## Fase 0: Persistencia y bootstrap sin impacto funcional

Objetivo:
- introducir SQLite, migraciones y bootstrap sin tocar la logica de trading

Trabajo:
- crear modulo `src/persistence/`
- aplicar migraciones al arranque
- guardar `strategy_instances`
- guardar `strategy_state` aunque sea vacio
- guardar `plans`, `execution_reports` y `event_log` minimos

Resultado esperado:
- el bot sigue ejecutando igual
- ya existe suelo persistente para los pasos siguientes

No hacer aun:
- `legs`
- `entry_groups`
- interprete completo de `actions`

## Fase 1: Instrumentar el camino legacy

Objetivo:
- obtener trazabilidad sin cambiar comportamiento de broker

Trabajo:
- `main.py` sigue llamando al analisis legacy
- antes de ejecutar, se construye un `synthetic_plan` a partir de la senal
- `trading.apply_signal()` sigue siendo quien realmente opera
- despues se persisten:
  - `plan`
  - `execution_report`
  - `event_log`

Resultado esperado:
- misma operativa que hoy
- nueva telemetria estructurada

Valor real:
- ya puedes auditar que quiso hacer cada estrategia
- ya puedes comparar decision y ejecucion real

## Fase 2: Introducir `context`, `state` y adaptador de runtime

Objetivo:
- mover el runtime desde "senal suelta" hacia "decision estructurada"

Trabajo:
- crear `StrategyContextBuilder`
- crear `StrategyStateStore`
- crear `StrategyRuntimeAdapter`
- `main.py` deja de pensar solo en `DataFrame`
- para cada estrategia:
  - si expone `decide(context, state)`, se usa el contrato v1
  - si no, se usa el adaptador legacy

Resultado esperado:
- coexisten estrategias legacy y v1
- ambas producen `plan`

Regla:
- aunque una estrategia siga siendo legacy, el scheduler ya debe hablar en
  terminos de `decision`

## Fase 3: Introducir el interprete de `actions`

Objetivo:
- sustituir la traduccion fija `buy/sell/none -> ordenes`

Trabajo:
- crear `PlanInterpreter`
- crear `ExecutionEngine`
- reutilizar helpers tecnicos de `trading.py`
- mover la inteligencia de ejecucion desde `apply_signal()` al interprete

Primer subset razonable de `actions`:
- `open_position`
- `add_to_position`
- `close_position`
- `reduce_position`
- `move_stop_loss`

Transicion recomendada:
- `trading.apply_signal()` no se elimina de golpe
- se convierte en un wrapper legacy que traduce su senal a `plan` y delega al
  interprete nuevo

Resultado esperado:
- mismo modulo tecnico de broker
- nuevo contrato de ejecucion

## Fase 4: Activar recursos canonicos y ownership real

Objetivo:
- materializar `legs`, `entry_groups`, `fills` y ownership por instancia

Trabajo:
- poblar tablas canonicas
- registrar `leg_id`, `entry_group_id` y `fill_id`
- dejar de pensar en "una posicion por magic" como unidad primaria
- introducir lecturas derivadas para `views`

Resultado esperado:
- soporte real para entradas independientes
- cierres y parciales no ambiguos

## Fase 5: Estado estrategico persistente completo

Objetivo:
- permitir estrategias con memoria propia real

Trabajo:
- el runtime carga `state` al principio de cada ciclo
- la estrategia devuelve `next_state`
- el motor persiste `next_state` con control de `revision`
- se define politica de recovery ante crash o reinicio

Resultado esperado:
- cooldowns, pyramiding, contadores y reglas de sesion sobreviven reinicios

## Fase 6: Convergencia de GUI y builder

Objetivo:
- quitar duplicacion y alinear la superficie de usuario con el runtime nuevo

Trabajo GUI:
- la GUI deja de ser registro paralelo de estrategias
- consume `read models` o servicios de consulta
- deja de depender de heuristicas por `magic_number` como unico eje

Trabajo builder:
- el guardado debe pasar por `handle_save_new()` o `handle_save_edit()`
- no debe llamar directo a `generate_strategy_file()` desde la GUI
- el builder legacy queda etiquetado como "signal strategy builder"
- si se crea un builder v2, debe generar contrato `decide(context, state)`

Resultado esperado:
- una sola fuente de verdad
- menos divergencia entre runtime y GUI

## Fase 7: Deprecacion controlada del contrato legacy

Objetivo:
- retirar `get_last_signal()` solo cuando el sistema nuevo ya sea estable

Reglas:
- primero advertencia
- luego modo dual por config
- luego modo `v1_only`
- por ultimo retirada real

No hacer:
- borrar compatibilidad legacy demasiado pronto

## Orden recomendado de cambios por archivo

### `main.py`

Primero:
- extraer bootstrap de persistencia
- introducir construccion de `plan` sintetico
- introducir runtime adapter

Despues:
- dejar de llamar a `_analyze_strategy()` como contrato final
- pasar a algo tipo `decide_strategy()`

Ultimo:
- aislar el loop en servicios mas pequenos

### `trading.py`

Primero:
- conservar helpers MT5 y de normalizacion

Despues:
- introducir interprete nuevo usando esos helpers

Ultimo:
- dejar `apply_signal()` como adapter legacy

### `gui_charts.py`

Primero:
- no tocar la UX principal
- solo corregir puntos de integracion errados

Despues:
- pasar lectura de estado y operaciones al read model persistido

Ultimo:
- rediseñar builder y vista de estrategia para recursos canonicos

### `strategies/builder.py`

Primero:
- centralizar uso correcto desde GUI

Despues:
- decidir si sigue como builder legacy o si nace `builder_v2`

Ultimo:
- generar estrategias del contrato nuevo

## Feature flags recomendados

Para migrar sin trauma, conviene usar flags explicitos.

Minimos recomendados:
- `PERSISTENCE_ENABLED`
- `LEGACY_SIGNAL_OBSERVABILITY_ENABLED`
- `STRATEGY_RUNTIME_MODE = legacy | dual | v1_only`
- `PLAN_EXECUTOR_ENABLED`
- `CANONICAL_RESOURCES_ENABLED`
- `GUI_READMODEL_ENABLED`

Ventaja:
- rollback rapido
- pruebas parciales en demo o paper
- despliegue por fases

## Politica de compatibilidad

Durante la fase dual:
- una estrategia legacy debe poder seguir funcionando sin cambios
- una estrategia v1 no debe depender de hacks del camino legacy
- el motor debe registrar de forma uniforme ambas

Compatibilidad minima que hay que preservar:
- discovery de estrategias
- `magic_number` legacy mientras siga existiendo la ruta vieja
- lectura de comentarios y marcadores en GUI
- operativa actual en cuentas donde ya funciona

## Que NO conviene hacer

1. Reescribir primero la GUI.
2. Introducir `legs` solo en memoria sin persistencia.
3. Cambiar comportamiento de trading y persistencia en un mismo paso grande.
4. Obligar al builder actual a soportar toda la v1 de golpe.
5. Borrar `apply_signal()` antes de tener interprete estable.
6. Romper estrategias legacy solo por pureza arquitectonica.

## Criterios de exito por fase

### Exito Fase 0
- la base SQLite se crea
- migraciones aplican
- no cambia la operativa

### Exito Fase 1
- cada decision deja `plan`, `report` y `events`
- la operativa sigue igual

### Exito Fase 2
- una estrategia v1 corre junto a estrategias legacy
- ambas pasan por el mismo scheduler

### Exito Fase 3
- el interprete ejecuta al menos el subset basico de `actions`
- `apply_signal()` pasa a ser compatibilidad, no contrato central

### Exito Fase 4
- existen `legs` y `entry_groups` reales
- una estrategia puede tener entradas independientes

### Exito Fase 5
- el `state` sobrevive reinicios y se versiona

### Exito Fase 6
- la GUI consulta el nuevo modelo sin duplicar runtime

### Exito Fase 7
- el contrato legacy puede apagarse por config sin romper el sistema nuevo

## Recomendacion final

La pieza mas importante para no romper el proyecto no es la base de datos ni la
GUI.

Es el adaptador temporal entre:
- estrategias legacy que emiten `buy/sell/none`
- runtime nuevo que espera `context + state -> plan + next_state`

Si ese puente esta bien disenado, la migracion sera progresiva.

Si ese puente esta mal disenado, cada fase obligara a tocar demasiadas piezas a
la vez.
