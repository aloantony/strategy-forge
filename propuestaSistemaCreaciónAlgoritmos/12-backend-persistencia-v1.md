# Backend Persistencia V1

## Objetivo

Elegir un backend realista para guardar:
- `state`
- `event_log`
- recursos operativos canónicos
- reportes y vistas derivadas si hace falta

Sin esto, toda la arquitectura anterior se queda en modelo conceptual.

## Criterios de decision

La v1 necesita un backend que soporte bien:
- atomicidad
- consistencia
- concurrencia razonable
- queries simples y utiles
- append log para auditoria
- facilidad de backup
- facilidad de inspeccion
- complejidad operativa baja

## Opciones reales evaluadas

## Opcion A. JSON por archivo

Ejemplo:
- un JSON por `state`
- un JSON por `execution_report`
- un log NDJSON para eventos

### Ventajas

- extremadamente simple
- facil de abrir a mano
- cero dependencia externa

### Problemas

- concurrencia pobre
- dificil de consultar
- dificil de correlacionar entidades
- gestion mas fragil de atomicidad
- crecera mal cuando aumenten eventos y estrategias

### Veredicto

Buena para prototipos rapidos.
Demasiado debil para el supersistema como backend canonico principal.

## Opcion B. JSON + append log

Ejemplo:
- `state` en JSON atomico
- `event_log` en NDJSON append-only

### Ventajas

- sigue siendo simple
- separa snapshot y log

### Problemas

- ya empiezas a tener dos modelos de persistencia
- queries y joins siguen siendo pobres
- reconstruir `legs`, grupos y ownership se vuelve mas costoso

### Veredicto

Mejor que JSON puro.
Todavia demasiado artesanal como base canonica.

## Opcion C. SQLite

Ejemplo:
- una base local `trading_agent.db`
- tablas para `strategy_state`, `event_log`, `legs`, `entry_groups`,
  `pending_orders`, `fills`, `execution_reports`

### Ventajas

- sigue siendo embebido y sin servicio externo
- transacciones y atomicidad serias
- queries muy utiles
- indices
- concurrencia suficiente para una v1 local
- excelente equilibrio entre simplicidad y rigor
- facil de backup y copiar
- buena base para replay y auditoria

### Problemas

- menos trivial de inspeccionar que un JSON
- requiere pensar schemas e indices
- hay que manejar migraciones de esquema

### Veredicto

Es la mejor opcion para una v1 pragmatica y seria.

## Opcion D. Base externa grande

Ejemplo:
- PostgreSQL
- MySQL
- event store dedicado

### Ventajas

- escalado superior
- mejor concurrencia
- despliegues mas complejos

### Problemas

- sobrecarga operativa innecesaria para la v1
- mas dependencia de infraestructura
- complica mucho el setup inicial

### Veredicto

No recomendada para la v1.

## Decision recomendada

### Backend canonico v1

La recomendacion formal es:
- `SQLite` como backend canonico principal

### Complementos opcionales

Se pueden anadir despues:
- export de snapshots a JSON
- export de reportes a JSON
- export del event log a NDJSON

Pero como exportaciones o vistas, no como fuente primaria.

## Por que SQLite encaja con este sistema

Porque el sistema que estamos definiendo necesita:
- `state` versionado
- `event_log` append-only
- recursos relacionados entre si
- ownership por `instance_id`
- replay
- auditoria

SQLite resuelve eso mucho mejor que archivos sueltos.

## Que deberia ser canonico en SQLite

Tablas o conjuntos logicos recomendados:
- `strategy_state`
- `event_log`
- `legs`
- `entry_groups`
- `pending_orders`
- `fills`
- `execution_reports`

Opcionalmente:
- `materialized_views_metadata`
- `schema_migrations`

## Propuesta de organizacion minima

## 1. `strategy_state`

Responsabilidad:
- guardar el ultimo `state` canonico por `instance_id`

Campos minimos:
- `instance_id`
- `strategy_key`
- `symbol`
- `revision`
- `state_json`
- `updated_at`

## 2. `event_log`

Responsabilidad:
- guardar eventos append-only

Campos minimos:
- `event_id`
- `occurred_at`
- `event_type`
- `strategy_key`
- `instance_id`
- `plan_id`
- `action_id`
- `payload_json`

## 3. `legs`

Responsabilidad:
- representar la exposicion logica independiente

Campos minimos:
- `leg_id`
- `instance_id`
- `strategy_key`
- `symbol`
- `entry_group_id`
- `status`
- `requested_volume`
- `opened_volume`
- `remaining_volume`
- `avg_entry_price`
- `stop_loss`
- `take_profit`
- `opened_at`
- `closed_at`
- `tags_json`

## 4. `entry_groups`

Responsabilidad:
- agrupar `legs`

Campos minimos:
- `entry_group_id`
- `instance_id`
- `strategy_key`
- `symbol`
- `status`
- `root_leg_id`
- `created_at`
- `closed_at`
- `tags_json`

## 5. `pending_orders`

Responsabilidad:
- ordenes pendientes vivas o historicas

## 6. `fills`

Responsabilidad:
- eventos ejecutados inmutables con correlacion fuerte

## 7. `execution_reports`

Responsabilidad:
- resumen por plan listo para UI o consulta

## Dos principios clave de almacenamiento

## Principio 1. Eventos inmutables, estados mutables

- `event_log` y `fills` son append-only
- `strategy_state`, `legs`, `entry_groups` y `pending_orders` son estado actual
  mutable bajo reglas controladas

Esto da buen equilibrio entre:
- rendimiento operativo
- trazabilidad historica

## Principio 2. JSON donde aporta flexibilidad, columnas donde aporta query

No todo debe normalizarse al extremo.

Regla recomendada:
- columnas para ids, timestamps, status y campos usados en filtros
- JSON para payloads complejos o metadata flexible

Ejemplos:
- `instance_id`, `status`, `plan_id`, `occurred_at` como columnas
- `tags`, `payload`, `state_json` como JSON

## Atomicidad recomendada

La unidad minima de transaccion para una ejecucion relevante deberia cubrir:
- cambios de recursos operativos del motor
- escritura de eventos correspondientes
- persistencia del `next_state`
- escritura del `execution_report`

Idealmente:
- o todo queda confirmado
- o nada queda a medias

## Orden de persistencia recomendado

Secuencia conceptual:

1. abrir transaccion
2. insertar eventos iniciales
3. aplicar cambios sobre recursos
4. insertar eventos derivados
5. persistir `next_state`
6. persistir `execution_report`
7. commit

Nota:
- el detalle exacto depende de la integracion con broker
- algunos eventos de broker pueden requerir pasos intermedios

## Concurrencia en SQLite

SQLite no es para miles de writers, pero para esta v1 local encaja bien.

Modelo recomendado:
- evaluacion en paralelo si hace falta
- persistencia y mutacion operativa con serializacion controlada
- lock por simbolo en memoria del motor
- transacciones cortas en SQLite

Eso casa bien con lo que ya definimos arquitectonicamente.

## Politica de indices recomendada

Indices utiles desde v1:
- `strategy_state(instance_id)`
- `event_log(occurred_at)`
- `event_log(plan_id)`
- `event_log(action_id)`
- `event_log(instance_id, occurred_at)`
- `legs(instance_id, status)`
- `legs(entry_group_id)`
- `entry_groups(instance_id, status)`
- `fills(leg_id)`
- `execution_reports(plan_id)`

## Politica de migraciones

SQLite obliga a tomarse en serio las migraciones.

Decision v1:
- incluir tabla `schema_migrations`
- cada cambio compatible o incompatible se versiona
- los schemas logicos del sistema y los schemas fisicos de DB deben tener control
  de version separado

## Que NO haria en la v1

- no haria un event store externo
- no repartiria el state entre muchos archivos JSON
- no usaria un ORM pesado desde el primer dia
- no intentaria normalizar absolutamente todos los payloads

## Compromiso pragmatico recomendado

Arquitectura v1:
- SQLite como fuente primaria
- adaptadores Python simples
- JSON solo como formato de export o debugging

Eso te da:
- seriedad operativa
- baja complejidad
- capacidad de evolucion

## Ejemplo aplicado a tu estrategia

Si tu estrategia:
- abre entrada inicial
- anade dos piramides
- mueve stops
- cierra una leg concreta

SQLite permite guardar y consultar bien:
- el `state` actual
- los `legs` vivos y cerrados
- el `entry_group` de la campana
- los `fills`
- el historial de decisiones
- el `execution_report` por plan

Con JSONs sueltos eso se vuelve bastante mas fragil y engorroso enseguida.

## Decision actual

La recomendacion formal v1 es:
- `SQLite` como backend canonico principal
- exportaciones JSON o NDJSON como capa opcional
- eventos inmutables y estados mutables
- columnas para claves de consulta y JSON para payloads flexibles

