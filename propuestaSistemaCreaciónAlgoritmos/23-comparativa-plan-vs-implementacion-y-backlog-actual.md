# Comparativa Plan vs Implementacion y Backlog Actual

## Objetivo

Comparar:
- el plan del supersistema definido en esta carpeta
- con lo que el repo ya tiene implementado
- y con lo que el sprint activo (`TASK-019` a `TASK-026`) esta empujando

La idea no es juzgar si el sprint esta "mal".

La idea es ver con claridad:
- que partes van en direccion compatible con el plan
- que partes son solo extensiones tacticas del sistema legacy
- y que piezas del plan siguen sin empezar

## Resumen ejecutivo

La comparacion honesta es esta:

- el backlog actual NO esta implementando todavia el supersistema
- esta extendiendo el motor legacy para soportar una estrategia externa concreta
- algunas decisiones del sprint son compatibles con el plan futuro
- pero la arquitectura que se esta tocando sigue siendo la de:
  - `get_last_signal/get_last_signal_payload`
  - `main.py` como scheduler + integrador
  - `trading.py` como ejecutor procedural
  - `magic_number` como eje de ownership operativo

Dicho aun mas claro:

- el sprint actual es una solucion vertical para `primeraEstrategia.md`
- el plan de esta carpeta es una reconstruccion horizontal del sistema entero

No son la misma cosa.

## 1. Estado real del codebase hoy

## Ya implementado en codigo

### Multi-estrategia legacy

Existe y funciona en el modelo actual:
- discovery dinamico de estrategias
- `magic_number` por estrategia
- analisis paralelo por estrategia
- ejecucion serial bajo lock global

Archivos clave:
- `main.py`
- `gui_charts.py`
- `trading.py`

### Builder visual legacy

Ya existe:
- `strategies/builder.py`
- UI del builder en `gui_charts.py`
- guardado de estrategias `.py + .json`

Pero el builder sigue generando estrategias del contrato viejo:
- `prepare_dataframe`
- `compute_signals`
- `get_last_signal`
- `get_last_signal_payload`

### Piramidado legacy parcial

Esto si parece ya implementado:
- `main.py` ya parsea `pyramiding` y `atr_value` en el payload
- `main.py` ya decide entre `apply_signal()` y `apply_pyramid_signal()`
- `trading.py` ya tiene `get_all_positions()`
- `trading.py` ya tiene `_send_order(..., sl_price, tp_price)`
- `trading.py` ya tiene `apply_pyramid_signal()`

Conclusion:
- `TASK-023` si parece materializado en codigo
- pero dentro del modelo legacy

## Aun no implementado en codigo

### Persistencia del plan nuevo

No existe en la practica:
- no hay `src/persistence/`
- no hay bootstrap SQLite
- no hay migraciones
- no hay `strategy_state`
- no hay `plans`
- no hay `execution_reports`
- no hay `event_log`
- no hay `legs`
- no hay `entry_groups`

### Contrato de estrategia v1

No existe en runtime:
- no hay `STRATEGY_API_VERSION`
- no hay `decide(context, state)`
- no hay adaptador runtime hacia `plan + next_state`

### Recursos canonicos

No existen:
- `leg`
- `entry_group`
- targeting por `leg_id`
- ownership canonico por `instance_id`

### Observabilidad del plan nuevo

No existe:
- no hay `plan_id`
- no hay `action_id`
- no hay `execution_report`
- no hay `event_log` canonico

## 2. Que esta implementando realmente el sprint actual

El sprint activo, segun `agents/context.md` y `agents/tasks.md`, esta centrado
en tres capas muy concretas para una estrategia externa:

1. ADX + DI y cruce.
2. Piramidado.
3. Sizing dinamico y riesgo agregado.

Eso ya dice mucho.

No esta planteado como:
- rediseñar el runtime
- introducir persistencia canonica
- pasar a `context + state -> plan + next_state`

Esta planteado como:
- permitir una estrategia nueva dentro del marco existente

## Tareas completadas del sprint

### `TASK-019`

Terminada como spec.

Aporta:
- disenio de ADX/+DI/-DI
- disenio del cruce

Todavia no aporta:
- implementacion efectiva en `builder.py`

### `TASK-020`

Terminada como spec.

Aporta:
- disenio de piramidado

### `TASK-021`

Terminada como spec.

Aporta:
- disenio de sizing dinamico y control de riesgo

### `TASK-023`

Terminada y visible en codigo.

Implementa:
- soporte para multiples posiciones bajo un mismo `magic_number`
- `apply_pyramid_signal()`
- SL/TP absolutos via `_send_order()`
- dispatch desde `main.py`

## Tareas aun pendientes

### `TASK-022`

Pendiente:
- spec GUI para reflejar piramidado y widget de riesgo

### `TASK-024`

Pendiente:
- sizing dinamico real
- control de riesgo agregado real

### `TASK-025`

Pendiente:
- ADX/+DI/-DI en `builder.py`
- cruce entre velas
- generacion de `strategy_primera_estrategia.py`

### `TASK-026`

Pendiente:
- implementacion GUI segun spec de Grace

## 3. Compatibilidades reales entre el sprint y el plan

Hay varios puntos donde el sprint actual si va en una direccion util para el
plan, aunque aun no cambie de arquitectura.

## Compatibilidad A: la estrategia ya emite mas que una senal simple

El payload actual ya esta creciendo mas alla de:
- `buy/sell/none`

Ahora aparecen:
- `reason`
- `pyramiding`
- `atr_value`

Eso es una senal de transicion interesante:
- el contrato sigue siendo legacy
- pero ya admite intencion mas rica

## Compatibilidad B: se empieza a reconocer que una estrategia puede tener varias entradas

`apply_pyramid_signal()` y `get_all_positions()` aceptan la realidad de:
- varias entradas de una misma estrategia

Eso es conceptualmente compatible con el plan, porque el plan tambien necesita:
- entradas independientes
- piramidado

## Compatibilidad C: SL/TP por entrada concreta

El soporte de `_send_order(..., sl_price, tp_price)` va en la direccion correcta.

El plan necesita justamente:
- stops y targets no globales
- definidos por cada entrada

## Compatibilidad D: la estrategia sigue aislada del core

El sprint mantiene la regla de aislamiento del modulo de estrategia.

Eso encaja bien con el plan:
- la estrategia decide
- el motor ejecuta

## 4. Divergencias fuertes entre el sprint y el plan

Aqui esta la parte importante.

## Divergencia A: sigue mandando el modelo `signal -> execution`

El plan propone:

`context + state -> plan + next_state`

El sprint actual sigue usando:
- `get_last_signal`
- o `get_last_signal_payload`
- y luego `main.py` traduce eso a ejecucion

Eso significa:
- la estrategia aun no devuelve `actions`
- no devuelve `next_state`
- no tiene `decision` v1

## Divergencia B: el ownership sigue anclado a `magic_number`

El plan quiere ownership por:
- `instance_id`
- `leg_id`
- `entry_group_id`

El sprint actual sigue operando por:
- `magic_number`

Incluso el piramidado nuevo se apoya en:
- filtrar posiciones por `magic_number`
- identificar la ultima entrada por orden temporal

Eso resuelve el caso actual, pero no construye la ontologia nueva.

## Divergencia C: no hay recursos canonicos

El plan define:
- `leg`
- `entry_group`
- `fill`
- `pending_order`
- `position_view`

El sprint actual sigue hablando de:
- posiciones MT5
- ordenes enviadas
- comentarios del broker

No hay capa intermedia canonica.

## Divergencia D: no hay `state` estrategico persistente

El plan quiere que la estrategia recuerde:
- cooldowns
- contadores
- piramides
- memoria privada

El sprint actual no crea nada de eso.

El "estado" del piramidado se deduce al vuelo leyendo posiciones abiertas del
broker, no desde un `strategy_state` canonico.

## Divergencia E: sizing y riesgo siguen en la capa de ejecucion

Segun las specs del sprint, el sizing dinamico y el control de riesgo agregado
los calcula la capa de ejecucion a partir de payloads del modulo de estrategia.

Eso diverge de la filosofia mas fuerte del plan, donde la estrategia deberia
decidir mucha mas logica de negocio y devolver un `plan` ya rico.

Dicho simple:
- el sprint mantiene la estrategia como emisora de senales enriquecidas
- el plan quiere convertirla en emisora de decisiones

## Divergencia F: no hay trazabilidad canonica

El plan quiere:
- `plan_id`
- `action_id`
- `execution_report`
- `event_log`

El sprint actual no crea nada de eso.

Por tanto:
- no hay replay serio
- no hay auditoria fuerte
- no hay base aun para reconciliacion canonica

## Divergencia G: la GUI sigue desacoplada del runtime nuevo

El plan quiere convergencia GUI/runtime.

Pero hoy la GUI:
- mantiene su propio registro de estrategias
- y al guardar sigue llamando directo a `generate_strategy_file()`

Eso encaja con el modelo viejo, no con el plan de fuente unica de verdad.

## 5. Comparacion por fases del plan de adopcion

## Fase 0 del plan: persistencia y bootstrap

Estado real:
- no empezada

## Fase 1 del plan: instrumentar el camino legacy con `plans/reports/events`

Estado real:
- no empezada

## Fase 2 del plan: `context`, `state` y runtime adapter

Estado real:
- no empezada

Hay una pseudo-transicion pequena:
- el payload legacy tiene mas campos

Pero eso no equivale aun a runtime adapter v1.

## Fase 3 del plan: interprete de `actions`

Estado real:
- no empezada

Lo que existe es:
- branching adicional en `main.py`
- y una nueva funcion procedural en `trading.py`

Eso no es aun un interprete de `actions`.

## Fase 4 del plan: recursos canonicos

Estado real:
- no empezada

## Fase 5 del plan: state persistente completo

Estado real:
- no empezada

## Fase 6 del plan: convergencia GUI y builder

Estado real:
- no empezada

## Fase 7 del plan: deprecacion del contrato legacy

Estado real:
- muy lejos aun

## 6. Lectura correcta de la situacion

La lectura correcta no es:
- "el sprint contradice el plan"

La lectura correcta es:
- el sprint resuelve una necesidad inmediata dentro del marco legacy
- mientras el plan de esta carpeta define la arquitectura que aun no se ha
  empezado a implementar

Eso tiene una consecuencia importante:

Si el proyecto sigue solo el backlog actual, avanzara en funcionalidades
concretas, pero tambien profundizara deuda en el modelo legacy.

Si despues quieres migrar al supersistema, parte de lo hecho seguira valiendo,
pero parte habra que envolver o rehacer.

## 7. Que piezas del sprint son reutilizables en el plan

Aun asi no todo se perderia.

Reutilizable casi seguro:
- formulas de ADX/+DI/-DI
- logica de cruce
- heuristica de piramidado
- formulas de sizing y riesgo
- mejoras de `_send_order()` para SL/TP absolutos

Reutilizable con wrapper o refactor:
- parseo de payload enriquecido
- lectura de posiciones por `magic_number`
- GUI de riesgo

Probablemente desechable o muy transitorio:
- branching directo en `main.py` entre `apply_signal()` y `apply_pyramid_signal()`
- usar `magic_number` como eje semantico primario de ownership
- seguir extendiendo el builder solo como generador de senales legacy

## 8. Conclusiones claras

## Conclusion 1

El backlog activo esta implementando una evolucion del sistema actual, no el
supersistema.

## Conclusion 2

El avance real mas importante del sprint en codigo es:
- piramidado procedural dentro del modelo legacy

## Conclusion 3

Las piezas mas nucleares del plan siguen completamente pendientes:
- persistencia
- `state`
- `plan/actions`
- recursos canonicos
- `execution_report`
- `event_log`
- contrato de estrategia v1

## Conclusion 4

Hay compatibilidad conceptual parcial:
- formulas
- enriquecimiento de payload
- multiples entradas

Pero no compatibilidad arquitectonica fuerte todavia.

## Conclusion 5

Si quieres usar el sprint actual como puente hacia el plan, la maniobra correcta
sera:
- dejar de seguir añadiendo logica en `main.py` y `trading.py` como casos
  especiales
- y empezar la adopcion incremental por Fase 0/Fase 1 del plan

## Dictamen final

Comparado con el plan de esta carpeta, el repo esta hoy en esta situacion:

- implementacion del supersistema: casi toda pendiente
- extensiones legacy para una estrategia concreta: activas y parcialmente
  implementadas
- backlog actual: tactico y vertical
- plan del supersistema: estrategico y horizontal

Las dos lineas pueden convivir un tiempo.

Pero si no se conectan pronto, el backlog actual empezara a alejarse cada vez
mas de la arquitectura objetivo.
