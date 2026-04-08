# Plan Migraciones SQL V1

## Objetivo

Definir como convertir el schema fisico v1 en migraciones reales, ordenadas,
versionables y aplicables en un proyecto local con SQLite.

## Principio rector

La base no debe crearse "a mano" ni con SQL disperso por el codigo.

Debe existir:
- una secuencia de migraciones versionadas
- una tabla `schema_migrations`
- un bootstrap determinista al arrancar

## Filosofia de migraciones

La v1 debe priorizar:
- claridad
- reversibilidad conceptual
- facilidad de inspeccion
- baja magia

No recomiendo en la v1:
- generacion automatica opaca de migraciones
- ORM con autogenerate
- mezclar DDL en runtime dentro de servicios de negocio

## Ubicacion recomendada en este repo

Dado que `src/` esta libre, la propuesta es:

```text
src/
  persistence/
    __init__.py
    sqlite.py
    migrations/
      0001_initial_schema.sql
      0002_indexes.sql
      0003_views_optional.sql
```

Regla:
- una migracion por archivo
- nombre numerico creciente
- prefijo de 4 digitos suficiente para la v1

## Tabla `schema_migrations`

Ya quedo definida en el schema fisico:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version      INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    applied_at   TEXT NOT NULL
);
```

## Estrategia de corte de migraciones

Aunque tecnicamente podria meterse todo en un solo archivo, recomiendo separar:

### 0001. `initial_schema`

Incluye:
- `schema_migrations`
- `strategy_instances`
- `symbol_books`
- `strategy_state`
- `plans`
- `execution_reports`
- `action_reports`
- `entry_groups`
- `legs`
- `pending_orders`
- `fills`
- `event_log`

### 0002. `indexes`

Incluye:
- indices recomendados
- cualquier indice extra descubierto en pruebas iniciales

### 0003. `views_optional`

Incluye solo derivadas opcionales, nunca tablas canonicas.

Ejemplos:
- vista de `open_legs`
- vista de `open_groups`
- vista de `latest_reports`

## Por que separar schema e indices

Ventajas:
- lectura mas limpia
- rollback conceptual mas facil
- tuning posterior sin tocar tablas base

## Contenido recomendado de `0001_initial_schema.sql`

Orden recomendado:

1. `schema_migrations`
2. `strategy_instances`
3. `symbol_books`
4. `strategy_state`
5. `plans`
6. `execution_reports`
7. `action_reports`
8. `entry_groups`
9. `legs`
10. `pending_orders`
11. `fills`
12. `event_log`

## Por que este orden

Regla:
- primero identidades y ownership
- despues planes y reportes
- despues recursos operativos
- por ultimo el log append-only

## Contenido recomendado de `0002_indexes.sql`

Indices que deberian vivir ahi:

### `strategy_instances`

- `(strategy_key, symbol)`
- `(status)`

### `strategy_state`

- `(revision)`

### `plans`

- `(instance_id, created_at)`
- `(iteration_id)`
- `(status)`

### `execution_reports`

- `(instance_id, created_at)`

### `action_reports`

- `(status)`
- `(plan_id)`

### `entry_groups`

- `(instance_id, status)`
- `(symbol, status)`

### `legs`

- `(instance_id, status)`
- `(entry_group_id)`
- `(symbol, status)`

### `pending_orders`

- `(instance_id, status)`
- `(broker_order_id)`

### `fills`

- `(leg_id)`
- `(entry_group_id)`
- `(broker_deal_id)`
- `(occurred_at)`

### `event_log`

- `(occurred_at)`
- `(plan_id)`
- `(action_id)`
- `(instance_id, occurred_at)`
- `(leg_id)`

## Vistas opcionales de `0003_views_optional.sql`

Estas vistas no deben convertirse en acoplamientos fuertes de negocio, pero si
pueden ahorrar queries repetitivas.

Ejemplos recomendados:

### `v_open_legs`

```sql
CREATE VIEW IF NOT EXISTS v_open_legs AS
SELECT *
FROM legs
WHERE status IN ('open', 'reducing');
```

### `v_open_entry_groups`

```sql
CREATE VIEW IF NOT EXISTS v_open_entry_groups AS
SELECT *
FROM entry_groups
WHERE status IN ('open', 'partially_closed');
```

### `v_working_pending_orders`

```sql
CREATE VIEW IF NOT EXISTS v_working_pending_orders AS
SELECT *
FROM pending_orders
WHERE status IN ('working', 'partially_filled');
```

## Formato interno del archivo SQL

Reglas recomendadas:

- una seccion por tabla
- comentarios breves
- `IF NOT EXISTS` en creacion
- no mezclar datos seed salvo necesidad real

## Datos seed

La v1 no deberia meter seeds de negocio en migraciones.

Si hace falta inicializacion operacional, debe hacerla el bootstrap del motor.

Ejemplos:
- crear `symbol_books` cuando se use un simbolo nuevo
- crear `strategy_instances` al registrar una instancia

## Politica de cambios futuros

Regla:
- no editar migraciones ya aplicadas en produccion local
- cualquier cambio nuevo entra como nueva migracion

Ejemplos:
- anadir columna -> nueva migracion
- crear indice -> nueva migracion
- nueva vista -> nueva migracion

## Politica de rollback

En SQLite, rollback operacional real de DDL no siempre es la mejor estrategia.

Decision pragmatica v1:
- forward-only migrations
- si una migracion esta mal, se corrige con otra posterior

Motivo:
- menos complejidad
- menos falsa sensacion de seguridad

## Bootstrap de migraciones

Secuencia recomendada al iniciar el sistema:

1. abrir conexion SQLite
2. asegurar `PRAGMA` deseados
3. asegurar existencia de `schema_migrations`
4. listar archivos de migracion
5. leer versiones ya aplicadas
6. aplicar pendientes en orden
7. insertar registro en `schema_migrations` tras cada commit exitoso

## Atomicidad por migracion

Regla:
- cada migracion se aplica en su propia transaccion

Consecuencia:
- si falla `0002`, `0001` queda consistente
- no se deja una migracion a medias

## Formato de version recomendado

Regla:
- el nombre de archivo empieza por version numerica
- la tabla guarda `version` y `name`

Ejemplo:

Archivo:
- `0002_indexes.sql`

Registro:
- `version = 2`
- `name = '0002_indexes.sql'`

## Validaciones del runner de migraciones

El runner deberia comprobar:
- que no haya versiones repetidas
- que la secuencia sea creciente
- que el archivo aplicado coincida con el nombre esperado
- que el SQL no este vacio

## Estrategia de migraciones para desarrollo

Durante desarrollo temprano:
- se puede borrar la DB y recrear desde cero

Pero incluso ahi:
- las migraciones deben existir
- no solo helpers de `create_all`

Motivo:
- obliga a que el schema sea reproducible

## Estrategia para tests

Recomendacion v1:
- base SQLite temporal por test o por suite
- aplicar migraciones reales
- no usar schema alternativo para tests

Eso evita divergencia entre:
- schema productivo
- schema de test

## Señales de que hace falta nueva migracion

Crear migracion nueva cuando:
- cambie el schema fisico
- aparezcan nuevos indices operativos
- se creen vistas recurrentes
- se necesiten nuevas restricciones

No crear migracion nueva solo por:
- cambios en payloads JSON internos
- cambios en helpers Python que no alteren el schema

## Decision actual

La propuesta v1 es:
- migraciones SQL planas en `src/persistence/migrations/`
- runner propio y simple
- `0001_initial_schema.sql`
- `0002_indexes.sql`
- `0003_views_optional.sql`
- forward-only migrations
- bootstrap determinista al arrancar

