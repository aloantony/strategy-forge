# Politica De Concurrencia Y Reintentos De Ejecucion v1

## Objetivo

Fijar como debe comportarse el motor cuando varias decisiones conviven en el
tiempo y cuando el broker responde con errores, timeouts o estados ambiguos.

Este documento no define logica de trading.

Define logica operativa del motor:
- que puede correr en paralelo
- que debe serializarse
- cuando hay que revalidar antes de ejecutar
- cuando se reintenta y cuando no
- como evitar doble ejecucion

## Diagnostico del sistema actual

Hoy el repo ya tiene dos ideas correctas, pero parciales:

1. Analisis paralelo por estrategia en `main.py`.
2. Bloqueo global de ejecucion con `ORDER_EXECUTION_LOCK`.

Y en `trading.py` ya existe un helper tecnico:
- `order_send_with_filling_retry()`

Pero ese helper solo resuelve una cosa:
- probar distintos `filling modes`

No resuelve de forma completa:
- concurrencia por simbolo
- revalidacion de estado antes de ejecutar
- idempotencia por `plan_id` y `action_id`
- reconciliacion tras timeout o respuesta ambigua
- politicas distintas por tipo de error

## Principio general

La politica correcta para v1 es:

`decision paralela, mutacion controlada, broker conservador, reintentos no ciegos`

Eso se traduce asi:
- las estrategias pueden decidir en paralelo
- las mutaciones sobre un mismo libro de simbolo no
- el broker nunca debe recibir dos mutaciones concurrentes sin control
- un retry nunca debe dispararse sin reconciliar antes el estado real

## Fases del pipeline y su politica

## Fase A: snapshot y contexto

Puede ejecutarse en paralelo mientras se garantice que cada estrategia ve una
foto consistente.

Permitido en paralelo:
- carga de mercado por timeframe
- construccion de `context`
- carga de `state`
- calculo de decision

Regla:
- cada decision debe correr contra un snapshot inmutable para ese ciclo

## Fase B: validacion y encolado de planes

Puede ejecutarse en paralelo porque aun no hay efectos externos.

Trabajo tipico:
- validar schema de `plan`
- completar ids faltantes
- persistir `plan_received`
- clasificar recursos/simbolos afectados

## Fase C: ejecucion real

Aqui ya no vale el paralelismo libre.

Debe haber control explicito de concurrencia.

## Niveles de concurrencia

## 1. Concurrencia de decision

Permitida.

Unidad:
- `strategy_instance`

Dos instancias pueden decidir a la vez si:
- leen solo `context`
- leen su `state`
- no mutan broker ni recursos compartidos

## 2. Concurrencia logica de ejecucion

Restringida por `symbol_book`.

Unidad:
- `symbol`

Regla v1:
- no se intercalan mutaciones de planes distintos sobre el mismo simbolo

Eso significa:
- si dos planes tocan `EURUSD`, se ejecutan en cola
- si un plan toca `EURUSD` y otro `XAUUSD`, logicamente pueden avanzar por
  carriles distintos

## 3. Concurrencia fisica de broker

Conservadora.

Regla v1:
- todas las llamadas mutantes a MT5 deben pasar por un `broker_session_lock`
  global

Razon:
- el adapter Python/terminal de MT5 no debe asumirse thread-safe
- el sistema actual ya trabaja con un lock global
- es mejor perder algo de paralelismo que introducir dobles envios o estados
  raros

Conclusion importante:
- v1 permite paralelismo logico por simbolo
- pero el paso final de broker I/O sigue siendo serial globalmente

## Locks recomendados

## `symbol_book_lock(symbol)`

Obligatorio para:
- resolver targets finales
- revalidar estado de ejecucion
- ejecutar acciones que mutan recursos del simbolo
- persistir cambios canonicos del simbolo

Semantica:
- un solo escritor por simbolo a la vez

## `broker_session_lock`

Obligatorio en v1 para:
- `order_send`
- `positions_get`
- `orders_get`
- lecturas de reconciliacion inmediatamente ligadas a una mutacion

Nota:
- no todo acceso de solo lectura del sistema necesita este lock
- pero toda secuencia critica "leer broker -> enviar -> releer broker" si

## `state_revision` por instancia

No hace falta un lock largo por instancia si usamos revision optimista.

Regla:
- `strategy_state` se actualiza con control de `revision`
- si hay conflicto, se registra y se fuerza nueva sincronizacion

Como la mutacion fuerte la gobierna el `symbol_book_lock`, en la practica los
conflictos deberian ser raros.

## Orden de ejecucion entre planes

Cuando varios planes esperan sobre el mismo simbolo, el orden debe ser
determinista.

Criterio recomendado v1:
1. `decision_ts` mas antiguo primero
2. si empatan, `plan_id` lexicografico

No conviene:
- orden no determinista por llegada de threads
- fairness "misteriosa"
- priorizacion oculta por tipo de estrategia

## Orden de acciones dentro de un plan

Regla:
- las `actions` de un mismo `plan` se ejecutan en el orden declarado

No se intercalan con acciones de otro plan sobre el mismo simbolo.

Esto es importante para secuencias como:
- cerrar y luego abrir
- reducir y luego mover stop

## Revalidacion antes de ejecutar

Esta es una regla central.

Una estrategia decide con un snapshot anterior.

Antes de ejecutar de verdad, el motor debe:
- adquirir `symbol_book_lock`
- refrescar vista local y vista broker del simbolo
- releer recursos owned y targets
- volver a resolver selectores
- verificar ownership y estado

Solo despues de eso puede mandar la orden.

## Que se revalida exactamente

Minimo v1:
- que el target sigue existiendo
- que el target sigue perteneciendo a la instancia
- que el `symbol_book` no esta en conflicto
- que la accion sigue siendo tecnicamente aplicable
- que la accion no fue ya ejecutada o terminalizada

Ejemplos:
- un `move_stop_loss` sobre un `leg` ya cerrado debe rechazarse como stale
- un `close_position` sobre un grupo ya cerrado no debe reabrir nada ni hacer
  magia
- un `open_position` puede seguir siendo valido aunque haya cambiado el precio,
  pero debe recalcularse con quote actual

## Politica ante planes stale

Si una revalidacion falla por cambio de estado:
- el motor no reinterpretara la estrategia por su cuenta
- la accion se marca como `stale_rejected` o equivalente
- el sistema esperara a la siguiente decision del scheduler

Razon:
- reinterpretar un plan viejo con estado nuevo seria inventar trading logic

## Politica de reintentos

## Regla madre

Nunca se reintenta ciegamente una mutacion de broker.

Antes de reintentar hay que responder:
- fallo de verdad
- o la accion pudo haberse ejecutado aunque la respuesta sea mala

## Tipos de resultado

### 1. Exito definitivo

No hay retry.

### 2. Error local determinista

Ejemplos:
- schema invalido
- target inexistente
- ownership invalido
- `lot_step` imposible tras normalizacion
- modo de cuenta incompatible

Politica:
- no retry
- rechazo definitivo

### 3. Rechazo tecnico definitivo del broker

Ejemplos:
- orden invalida
- stops invalidos despues de normalizacion
- volumen invalido
- mercado no permite ese tipo de orden

Politica:
- no retry ciego
- registrar rechazo
- solo una decision nueva de estrategia puede volver a intentarlo

### 4. Error temporal o transitorio

Ejemplos tipicos:
- broker ocupado
- trade context busy
- no connection temporal
- price changed
- requote
- off quotes

Politica:
- retry acotado
- siempre con reconciliacion previa

### 5. Resultado ambiguo

Ejemplos:
- `order_send()` devuelve `None`
- timeout
- se pierde la respuesta del terminal
- error donde no queda claro si la orden entro o no

Politica:
- primero reconciliar
- solo luego decidir si reintentar

## Que cuenta como retry y que no

Importante para v1:

El helper actual `order_send_with_filling_retry()` no debe contarse como varios
retries logicos.

Debe considerarse:
- una sola tentativa logica de ejecucion
- con fallback tecnico interno de `filling mode`

Razon:
- no cambia la intencion de trading
- solo busca un modo de envio compatible con el broker

## Presupuesto de reintentos v1

Recomendacion pragmatica:
- maximo 3 intentos logicos por accion mutante
- `attempt_1` inicial
- hasta 2 retries reales adicionales

Backoff recomendado:
- retry 1: 250 ms
- retry 2: 750 ms

Con jitter pequeno opcional.

No conviene en v1:
- retries infinitos
- esperas largas
- loops agresivos dentro del mismo ciclo

## Regla de reconciliacion antes de retry

Antes de cualquier retry, el motor debe consultar el estado real.

Minimo:
- posiciones del simbolo
- ordenes pendientes del simbolo
- recursos owned de la instancia
- historial reciente si hace falta para detectar fills

Objetivo:
- comprobar si el efecto deseado ya ocurrio

## Resultado de la reconciliacion

### Caso A: el efecto ya ocurrio

Ejemplo:
- se quiso abrir long
- la respuesta fue ambigua
- pero ahora existe el `leg` o la posicion esperada

Politica:
- marcar `success_reconciled`
- no retry

### Caso B: el efecto no ocurrio y el error es retryable

Politica:
- reintentar si queda presupuesto

### Caso C: el estado es inconsistente o no concluyente

Politica v1:
- no encadenar retries infinitos
- marcar `reconciliation_failed` o estado equivalente
- pedir nuevo ciclo de decision

## Correlacion broker <-> action

Para reconciliar bien hace falta correlacion.

Decision v1:
- el ejecutor debe priorizar tokens compactos de correlacion en comentarios de
  broker antes que texto humano largo

Motivo:
- la razon humana ya vive en `plan`, `execution_report` y `event_log`
- el comentario de broker es un canal tecnico corto

Minimo recomendado en comentario:
- prefijo bot
- token corto de instancia
- token corto de accion o plan

No conviene gastar el comentario de broker en frases largas si eso reduce la
capacidad de reconciliacion.

## Politica por tipo de accion

## `open_position`

Puede reintentarse solo si:
- no hay evidencia de fill previo
- el error es temporal o ambiguo
- la revalidacion del simbolo sigue siendo correcta

En cada retry:
- refrescar quote
- recalcular precio derivado
- volver a validar volumen y stops tecnicos

## `close_position`

Es especialmente sensible a duplicados.

Antes de retry:
- comprobar si el target ya desaparecio
- o si el volumen ya se redujo

Si el target ya no existe:
- marcar exito reconciliado

## `reduce_position`

Misma politica que `close_position`, pero comprobando volumen restante.

No reintentar si:
- el volumen objetivo restante ya no coincide
- o el target quedo cerrado por otra accion

## `move_stop_loss` y `move_take_profit`

No conviene reintentar muchas veces.

Politica v1:
- maximo 1 retry real tras reconciliacion

Razon:
- si el target cambia rapido, la modificacion envejece enseguida

## `place_pending_order`

Retry permitido si:
- no aparece la orden pendiente esperada
- el broker devolvio error temporal o ambiguo

Si la orden ya aparece:
- exito reconciliado

## `cancel_pending_order`

Antes de retry:
- comprobar si la orden ya no existe

Si ya no existe:
- exito reconciliado

## Relacion entre persistencia y ejecucion

Debe mantenerse el patron de dos fases definido en el esquema fisico:

### Fase local previa

Con transaccion corta:
- registrar intento
- reservar ids
- dejar eventos de inicio

### Fase broker

Sin transaccion SQLite abierta larga:
- llamar al broker
- reconciliar si hace falta

### Fase local final

Con transaccion corta:
- persistir resultado
- actualizar recursos canonicos
- bump de revisiones
- emitir `execution_report`
- append en `event_log`

## Invariantes obligatorios

1. Ninguna accion mutante se ejecuta sin revalidacion bajo `symbol_book_lock`.
2. Ningun retry real ocurre sin reconciliacion previa.
3. Dos planes sobre el mismo simbolo no intercalan acciones.
4. El orden dentro de un plan lo decide la estrategia y el motor lo respeta.
5. La capa broker fisica se mantiene serial global en v1.
6. Todo intento queda trazado con `plan_id`, `action_id` y `attempt_no`.

## Escenarios canonicos

## Escenario 1: dos estrategias en el mismo simbolo

Caso:
- instancia A quiere abrir long en `EURUSD`
- instancia B quiere cerrar algo en `EURUSD`

Politica:
- ambas decisiones pueden calcularse en paralelo
- ambas entran a cola del `symbol_book` de `EURUSD`
- una ejecuta completa primero
- la segunda revalida despues y puede quedar stale o seguir siendo valida

## Escenario 2: timeout al abrir orden

Caso:
- `open_position`
- `order_send()` devuelve resultado ambiguo

Politica:
- no reenviar de inmediato
- reconciliar con broker
- si ya hay evidencia de apertura, marcar exito reconciliado
- si no la hay y el error era retryable, reintentar con presupuesto restante

## Escenario 3: mover SL mientras entra otra piramide

Caso:
- plan 1 quiere `move_stop_loss`
- plan 2 quiere `add_to_position`
- mismo simbolo e instancia

Politica:
- no intercalar
- una accion completa antes que la otra
- la segunda revalida con el nuevo estado resultante

## Decision final v1

La politica correcta para v1 es deliberadamente conservadora:
- decision paralela
- ejecucion serial por simbolo
- I/O broker serial global
- retries pocos
- nunca ciegos
- reconciliacion obligatoria

No maximiza throughput teorico.

Si maximiza algo mas importante para esta etapa:
- coherencia
- auditabilidad
- ausencia de dobles ejecuciones
- seguridad tecnica del supersistema
