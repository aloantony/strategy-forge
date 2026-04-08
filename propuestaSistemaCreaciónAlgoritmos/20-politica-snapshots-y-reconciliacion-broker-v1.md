# Politica De Snapshots Y Reconciliacion Con Broker v1

## Objetivo

Definir:
- que significa `snapshot` en el supersistema
- que snapshots existen
- cuando se crean
- cuanto duran
- cuando hay que reconciliar con el broker
- que pasa si el broker y el libro canonico divergen

Esta politica es critica porque ya fijamos dos cosas:
- la estrategia decide con un `context` de solo lectura
- la ejecucion revalida y puede reintentar con reconciliacion

Faltaba cerrar de donde sale exactamente esa "verdad" y como se corrige cuando
el mundo externo y el estado interno dejan de coincidir.

## Principio general

La politica correcta es esta:

`la estrategia decide sobre un snapshot estable; el motor ejecuta sobre un snapshot mas fresco; la reconciliacion repara la distancia entre libro canonico y broker`

Eso implica tres ideas:
- no se decide leyendo el broker en vivo a mitad de una estrategia
- no se ejecuta a ciegas sobre un snapshot viejo
- no se asume que DB y broker estan siempre alineados

## Fuentes de verdad y su jerarquia

Hay que distinguir verdades de distinto tipo.

## 1. Broker

Es la verdad externa para:
- posiciones vivas en cuenta
- ordenes pendientes vivas
- deals/fills realmente ocurridos
- SL/TP realmente aplicados

Si el broker y la DB discrepan sobre existencia o volumen real de una posicion u
orden, para la realidad externa manda el broker.

## 2. Libro canonico del motor

Es la verdad interna para:
- ownership por `instance_id`
- `leg`
- `entry_group`
- correlacion con `plan_id` y `action_id`
- historial interno y auditabilidad

Si el broker expone una posicion viva pero el motor aun no la proyecto bien a
`legs`, eso no invalida que el broker sea real; significa que falta reconciliar.

## 3. State de estrategia

Es la verdad solo para:
- memoria privada del algoritmo

Nunca debe usarse como verdad de:
- posiciones reales
- ordenes reales
- fills reales

## 4. Snapshot de mercado

Es la verdad observada para:
- velas
- quote
- spread
- anclas temporales de decision

## Tipos de snapshot

## 1. `decision_snapshot`

Es la foto estable con la que decide la estrategia.

Se crea:
- una vez por iteracion
- por simbolo y conjunto de dependencias de mercado

Incluye:
- mercado
- quote
- estado de cuenta
- libro canonico ya reconciliado mas reciente
- snapshot broker de lectura usado para construir ese contexto
- `state` de la estrategia en su revision correspondiente

Propiedad clave:
- es inmutable durante la decision

## 2. `execution_snapshot`

Es la foto fresca que usa el motor justo antes de ejecutar un `plan`.

Se crea:
- bajo `symbol_book_lock`
- inmediatamente antes de resolver y ejecutar acciones

Incluye al menos:
- vista local actual del simbolo
- vista broker actual del simbolo
- revision del libro
- revision del state
- quote actual para normalizacion tecnica

Propiedad clave:
- puede diferir del `decision_snapshot`
- si difiere materialmente, el plan puede quedar stale o necesitar solo
  re-normalizacion tecnica

## 3. `reconciliation_snapshot`

Es la foto usada para reparar deriva entre broker y libro canonico.

Se crea:
- tras resultados ambiguos
- al arrancar
- tras crash recovery
- al detectar drift
- periodicamente en simbolos activos

Incluye:
- posiciones broker del simbolo
- ordenes broker del simbolo
- deals recientes del simbolo
- libro canonico local del simbolo
- metadata de ultima reconciliacion conocida

## 4. `bootstrap_snapshot`

Es un caso especial de reconciliacion.

Se crea:
- al arrancar el proceso
- al reanudar tras una caida

Su objetivo no es decidir.
Su objetivo es:
- descubrir que realidad externa existe ya
- adoptar o marcar recursos externos
- dejar el libro local en estado coherente antes del trading normal

## Identidad minima de snapshot

Todo snapshot relevante debe tener metadata minima:
- `snapshot_id`
- `snapshot_kind`
- `symbol`
- `created_at`
- `iteration_id` si aplica
- `symbol_book_revision`
- `state_revision` si aplica
- `broker_probe_at`

En el caso de `decision_snapshot`, ademas conviene guardar:
- `last_closed_bar_at` por timeframe relevante
- `quote_at`

## Persistencia de snapshots

Decision v1:
- no crear tablas canonicas de "snapshot por tick"
- no persistir snapshots completas continuamente

Se persiste:
- manifiesto de snapshot en `plans`, `action_reports` y `event_log`
- payloads raw de reconciliacion solo cuando aportan valor real

## Que SI se guarda

Minimo recomendable:
- `decision_snapshot_id`
- `execution_snapshot_id`
- `reconciliation_snapshot_id` cuando exista
- revisiones usadas
- anclas temporales de mercado
- metadata de broker probe

## Que NO se guarda siempre

No por defecto:
- todas las posiciones raw del broker en cada iteracion
- todas las ordenes raw del broker en cada tick
- todas las velas completas duplicadas como snapshot aparte

Razon:
- seria caro
- duplicaria fuentes ya existentes
- choca con la decision de no tener tablas canonicas de snapshot continuo

## Contenido del `decision_snapshot`

El `decision_snapshot` que alimenta `context` debe representar:
- mercado consistente
- libro local ya reconciliado
- broker read basis mas reciente conocida para ese simbolo

Regla v1:
- todas las estrategias de la misma iteracion y mismo simbolo deben ver la
  misma foto de mercado y la misma base de ejecucion

Eso evita que:
- una estrategia decida con una posicion aun abierta
- y otra con la misma posicion ya cerrada
- dentro del mismo ciclo logico

## Frescura del `decision_snapshot`

Politica v1:
- un `decision_snapshot` solo vive para su iteracion
- no se arrastra al siguiente ciclo

Si un plan no se ejecuta en su ciclo natural:
- no se "recicla" con el mismo snapshot
- la siguiente iteracion genera decision nueva

## Contenido del `execution_snapshot`

Debe incluir lo necesario para resolver acciones sobre verdad reciente:
- recursos owned abiertos
- ordenes pendientes owned
- posiciones broker actuales
- ordenes broker actuales
- quote actual
- revisiones locales actuales

No tiene por que reconstruir todo el mundo.
Debe ser focalizado al simbolo y recursos afectados.

## Regla de edad maxima del `execution_snapshot`

Decision v1:
- un `execution_snapshot` solo es valido dentro de la seccion critica de la
  ejecucion del plan

Traducido:
- se toma
- se revalida
- se usa
- y se descarta

No se cachea para el siguiente plan del mismo simbolo si hubo mutacion de por
medio.

## Que diferencias entre snapshots importan

No toda diferencia vuelve stale un plan.

## Diferencias no materiales

No fuerzan rechazo por si mismas:
- cambio de quote
- cambio de spread
- cambio de pnl no realizado
- nuevas velas aun no evaluadas por la estrategia dentro de la misma iteracion

Respuesta:
- re-normalizar precio o stops si procede

## Diferencias materiales

Si pueden invalidar o cambiar targeting:
- target ya cerrado o desaparecido
- volumen ya reducido
- orden ya cancelada o ya existe
- ownership cambiado
- libro del simbolo mutado por otra ejecucion

Respuesta:
- marcar `stale_rejected` o estado equivalente
- esperar nueva decision

## Cuando reconciliar

## 1. Antes de las decisiones de cada iteracion

Politica v1:
- para cada simbolo con instancias activas, hacer una lectura broker ligera por
  iteracion

Lectura ligera:
- posiciones actuales del simbolo
- ordenes pendientes actuales del simbolo

Objetivo:
- que el `decision_snapshot` no nazca sobre una ficcion vieja

## 2. Justo antes de ejecutar un plan

Esto no es reconciliacion completa, pero si refresh de ejecucion.

Debe hacerse:
- siempre
- bajo `symbol_book_lock`

Objetivo:
- detectar drift reciente
- resolver targets con verdad fresca

## 3. Tras cualquier resultado ambiguo del broker

Obligatorio.

Ejemplos:
- `order_send()` devuelve `None`
- timeout
- respuesta incompleta
- duda real sobre si la orden entro

Aqui la reconciliacion debe ser completa.

## 4. Tras crash recovery o reinicio

Obligatorio antes de reanudar operativa automatica.

No se debe:
- seguir operando solo con la DB local
- asumir que nada cambio durante la caida

## 5. Periodicamente en simbolos activos

Decision v1:
- reconciliacion completa al menos cada 60 segundos para simbolos con actividad
  abierta o pendientes

Reconciliacion completa significa:
- posiciones
- ordenes
- deals recientes

Motivo:
- capturar actividad no observada
- reparar pequeñas desincronizaciones

## 6. Al detectar drift o actividad externa

Si aparece evidencia de:
- posicion inesperada
- orden inesperada
- fill inesperado
- recurso broker sin correlacion local

debe dispararse reconciliacion completa inmediata.

## Niveles de reconciliacion

## Nivel 0: refresh ligero

Lee:
- posiciones actuales
- ordenes actuales

No intenta:
- reconstruir deals historicos

Uso:
- pre-decision
- pre-execution

## Nivel 1: reconciliacion incremental completa

Lee:
- posiciones actuales
- ordenes actuales
- deals desde `last_reconciled_at - safety_window`

`safety_window` recomendado v1:
- 5 minutos

Uso:
- timer periodico
- tras drift pequeño
- tras error temporal/ambiguo

## Nivel 2: bootstrap o recovery reconciliation

Lee:
- posiciones actuales
- ordenes actuales
- deals de una ventana amplia reciente

Ventana recomendada v1:
- ultimas 24 horas

Uso:
- arranque
- recovery tras caida prolongada

Si aun asi no basta para reconstruir origen exacto:
- se permiten recursos sinteticos adoptados con origen
  `bootstrap_reconciliation`

## Algoritmo general de reconciliacion

1. Adquirir `symbol_book_lock(symbol)`.
2. Adquirir `broker_session_lock`.
3. Leer estado broker relevante del simbolo.
4. Leer libro canonico local del simbolo.
5. Correlacionar recursos broker con recursos locales.
6. Detectar:
   - coincidencias
   - faltantes locales
   - faltantes broker
   - actividad externa no atribuida
7. Aplicar reparaciones canonicas.
8. Persistir eventos, reportes de reconciliacion y bump de revisiones.
9. Liberar locks.

## Correlacion broker <-> recursos canonicos

La correlacion debe usar varias capas, en este orden:

1. `broker_order_id`, `broker_deal_id`, `broker_position_id` ya conocidos
2. tokens tecnicos en comentario de broker
3. simbolo + lado + volumen + proximidad temporal
4. contexto de accion en vuelo

Regla:
- no asignar ownership fuerte con heuristicas debiles si hay ambiguedad real

## Politica ante actividad externa o manual

Puede ocurrir que el broker muestre recursos que el motor no puede atribuir con
confianza.

Ejemplos:
- orden manual
- posicion abierta fuera del bot
- comentario sin tokens de correlacion
- fill ocurrido durante una caida y ya sin contexto claro

Politica v1:
- no apropiarse de ese recurso automaticamente a una estrategia
- registrarlo como `external_unowned`
- marcar el `symbol_book` como degradado en metadata o evento
- bloquear nuevas mutaciones automaticas de ese simbolo hasta que la
  reconciliacion lo deje claro o el usuario intervenga

Esto no es un limite financiero.
Es una proteccion tecnica para no cerrar o modificar algo que el motor no
entiende.

## Politica ante recursos locales que el broker ya no muestra

Si el libro local dice que algo existe pero el broker ya no:
- no se elimina silenciosamente
- se intenta explicar mediante deals recientes

Casos:
- una pending order desaparecio y hay cancelacion o fill -> actualizar estado
- una posicion desaparecio y hay close fill -> cerrar legs/grupo
- no hay evidencia suficiente -> marcar `reconciliation_inconclusive`

## Reparaciones permitidas por reconciliacion

La reconciliacion SI puede:
- crear fills faltantes
- cerrar legs que realmente ya estan cerradas
- marcar pending orders como filled/cancelled/expired
- crear recursos sinteticos adoptados en bootstrap
- actualizar ids broker conocidos
- bump de revisiones

La reconciliacion NO debe:
- inventar nueva logica de estrategia
- recalcular `next_state`
- reinterpretar setups
- disparar nuevas acciones de trading

## Recursos sinteticos adoptados

Caso especial importante:
- al arrancar, puede haber posiciones u ordenes abiertas del bot que la DB no
  conoce bien

Decision v1:
- si la correlacion con una instancia es suficientemente fuerte, el motor puede
  crear `entry_group` y `leg` sinteticos de adopcion

Deben quedar marcados con:
- `origin = bootstrap_reconciliation`
- evento explicito en `event_log`

Objetivo:
- continuar gestionando correctamente la exposicion real
- sin fingir que conocemos su historia completa

## Impacto sobre `context`

El `context` debe cargar metadata minima del snapshot de decision.

Campos recomendados en `run`:
- `decision_snapshot_id`
- `symbol_book_revision`
- `state_revision`

Y, cuando tenga sentido, metadata de anclaje:
- `quote_at`
- `last_closed_bar_at` por timeframe principal

No para que la estrategia consulte el broker.
Si para:
- trazabilidad
- debugging
- replay

## Politica de planes viejos

Un plan emitido contra un `decision_snapshot` viejo no se rescata ni se adapta.

Regla v1:
- si el plan no pudo ejecutarse y la realidad cambio materialmente, muere como
  plan stale

La siguiente iteracion producira otro.

## Paper y backtest

La politica conceptual es la misma:
- `decision_snapshot`
- `execution_snapshot`
- `reconciliation_snapshot`

La diferencia es la fuente:
- en paper/backtest, el simulador hace de broker

Ventaja:
- misma arquitectura mental
- distinta implementacion del proveedor de snapshot

## Eventos minimos de snapshot y reconciliacion

Catalogo recomendado:
- `decision_snapshot_created`
- `execution_snapshot_refreshed`
- `reconciliation_started`
- `reconciliation_diff_detected`
- `reconciliation_repair_applied`
- `reconciliation_inconclusive`
- `external_unowned_detected`
- `bootstrap_adoption_created`
- `symbol_book_resynchronized`

## Invariantes obligatorios

1. Toda decision usa un snapshot estable de iteracion.
2. Ninguna ejecucion mutante usa solo el snapshot de decision.
3. Toda mutacion se apoya en un `execution_snapshot` fresco.
4. Todo resultado ambiguo obliga a reconciliacion antes de retry.
5. El broker manda sobre existencia externa de posiciones, ordenes y fills.
6. El motor manda sobre ownership y proyeccion logica de `legs` y `entry_groups`.
7. La reconciliacion puede reparar libro, no inventar trading logic.
8. Recursos externos no atribuibles no se asignan a una estrategia por
   heuristica floja.

## Decision final v1

La politica cerrada para v1 es:
- `decision_snapshot` por iteracion
- `execution_snapshot` fresco bajo lock antes de ejecutar
- refresh ligero broker en cada iteracion para simbolos activos
- reconciliacion completa inmediata tras ambiguedad
- reconciliacion completa periodica cada 60 segundos en simbolos activos con
  exposicion o pendientes
- bootstrap reconciliation obligatoria al arrancar o recuperar
- broker como verdad externa
- libro canonico como verdad interna
- actividad externa no atribuible tratada como caso degradado, no como
  ownership inventado
