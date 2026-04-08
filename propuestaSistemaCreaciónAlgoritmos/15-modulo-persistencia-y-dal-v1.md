# Modulo Persistencia y DAL V1

## Objetivo

Definir el modulo minimo de acceso a datos para que el proyecto pueda usar
SQLite sin dispersar SQL y reglas transaccionales por `main.py`, `trading.py` o
la GUI.

## Principio rector

El codigo de negocio no debe hablar directamente con SQLite.

Debe existir una capa de persistencia con responsabilidades claras.

## Ubicacion recomendada

Propuesta de layout:

```text
src/
  persistence/
    __init__.py
    sqlite.py
    migrations/
    models.py
    repositories.py
    unit_of_work.py
    queries.py
    bootstrap.py
```

## Filosofia de la capa

La v1 debe ser:
- explicita
- pequena
- sin ORM pesado
- con SQL controlado
- con transacciones visibles

No recomiendo en la v1:
- SQL disperso por todo el proyecto
- repositorios con magia excesiva
- ORM que oculte demasiado la semantica

## Componentes minimos

## 1. `sqlite.py`

Responsabilidad:
- abrir conexiones
- aplicar `PRAGMA`
- devolver `row_factory`

Responsabilidades concretas:
- `connect(db_path) -> sqlite3.Connection`
- `configure_connection(conn) -> None`

## 2. `bootstrap.py`

Responsabilidad:
- ejecutar migraciones al arranque
- asegurar schema listo

Funciones recomendadas:
- `ensure_database(db_path)`
- `apply_pending_migrations(conn)`

## 3. `unit_of_work.py`

Responsabilidad:
- encapsular transacciones
- unificar `BEGIN IMMEDIATE`, `COMMIT`, `ROLLBACK`

Interfaz mental recomendada:

```python
with unit_of_work.write() as uow:
    ...
```

o:

```python
with unit_of_work.immediate() as uow:
    ...
```

## 4. `repositories.py`

Responsabilidad:
- agrupar operaciones CRUD y queries por agregado principal

Repositorios recomendados:
- `StrategyStateRepository`
- `PlansRepository`
- `ExecutionReportsRepository`
- `EntryGroupsRepository`
- `LegsRepository`
- `PendingOrdersRepository`
- `FillsRepository`
- `EventLogRepository`
- `SymbolBooksRepository`
- `StrategyInstancesRepository`

## 5. `queries.py`

Responsabilidad:
- consultas de lectura compuestas
- queries para UI, observabilidad o replay

Ejemplos:
- `get_open_legs_for_instance`
- `get_latest_report_for_plan`
- `get_events_for_instance_between`
- `get_group_with_open_legs`

## 6. `models.py`

Responsabilidad:
- definir tipos de transporte en Python

Puede usar:
- `dataclass`
- `TypedDict`
- o estructuras simples

Recomendacion v1:
- `dataclass` o `TypedDict` ligeros
- evitar acoplarse demasiado pronto a modelos complejos

## Capa recomendada por nivel

### Nivel bajo

- `sqlite.py`
- `bootstrap.py`
- `unit_of_work.py`

### Nivel medio

- `repositories.py`

### Nivel alto

- `queries.py`
- servicios de persistencia coordinados

## Servicios coordinadores recomendados

Ademas de repositorios, recomiendo dos servicios pequeños:

## 1. `ExecutionPersistenceService`

Responsabilidad:
- persistir el resultado final de una ejecucion

Ejemplo de responsabilidad:
- insertar o actualizar `plans`
- aplicar cambios en `legs`, `entry_groups`, `pending_orders`
- insertar `fills`
- persistir `strategy_state`
- insertar `execution_report`
- insertar `action_reports`
- insertar eventos

## 2. `ReplayQueryService`

Responsabilidad:
- servir queries de auditoria y replay

Ejemplos:
- reconstruir timeline por `plan_id`
- timeline de una `leg`
- timeline de una `instance_id`

## Frontera entre repositorio y servicio

Regla:
- repositorio = acceso a una tabla o agregado
- servicio = coordinacion entre varios repositorios en una transaccion

Ejemplo:
- `LegsRepository` sabe leer y escribir `legs`
- `ExecutionPersistenceService` sabe actualizar `legs`, `fills`,
  `execution_reports` y `event_log` juntos

## Interfaces minimas recomendadas

## `StrategyStateRepository`

Metodos minimos:
- `get(instance_id)`
- `upsert(state_record)`
- `update_if_revision_matches(instance_id, expected_revision, new_record)`

## `PlansRepository`

Metodos minimos:
- `insert(plan_record)`
- `get(plan_id)`
- `exists(plan_id)`
- `update_status(plan_id, status, updated_at)`

## `LegsRepository`

Metodos minimos:
- `insert(leg_record)`
- `get(leg_id)`
- `list_open_by_instance(instance_id)`
- `list_open_by_group(entry_group_id)`
- `update_leg_state(...)`
- `apply_fill_to_leg(...)`

## `EntryGroupsRepository`

Metodos minimos:
- `insert(group_record)`
- `get(entry_group_id)`
- `list_open_by_instance(instance_id)`
- `update_group_state(...)`

## `PendingOrdersRepository`

Metodos minimos:
- `insert(order_record)`
- `get(order_id)`
- `list_working_by_instance(instance_id)`
- `update_status(...)`

## `FillsRepository`

Metodos minimos:
- `insert(fill_record)`
- `list_by_leg(leg_id)`
- `list_by_group(entry_group_id)`

## `EventLogRepository`

Metodos minimos:
- `append(event_record)`
- `append_many(events)`
- `list_by_plan(plan_id)`
- `list_by_instance(instance_id, from_ts=None, to_ts=None)`

## `ExecutionReportsRepository`

Metodos minimos:
- `insert(report_record)`
- `get_by_plan(plan_id)`
- `list_latest_by_instance(instance_id, limit=50)`

## `SymbolBooksRepository`

Metodos minimos:
- `get(symbol)`
- `upsert(symbol_book_record)`
- `bump_revision(symbol, expected_revision)`

## `StrategyInstancesRepository`

Metodos minimos:
- `get(instance_id)`
- `upsert(instance_record)`
- `bump_revision(instance_id, expected_revision)`

## Patron Unit of Work recomendado

La capa UoW deberia exponer al menos:

```python
class UnitOfWork:
    conn
    strategy_state
    plans
    execution_reports
    action_reports
    entry_groups
    legs
    pending_orders
    fills
    event_log
    symbol_books
    strategy_instances
```

Y metodos:
- `commit()`
- `rollback()`

## Write patterns recomendados

### Patron A. Lectura simple

Para queries sin mutacion:
- conexion corta de solo lectura
- sin UoW compleja si no hace falta

### Patron B. Escritura simple

Para cambios pequenos:
- `with UnitOfWork.immediate()`

### Patron C. Persistencia final de ejecucion

Para resultados de una action o plan:
- servicio coordinador + UoW

## SQL inline vs SQL centralizado

Recomendacion v1:
- SQL de escritura y queries recurrentes centralizados en `repositories.py` y
  `queries.py`
- evitar SQL inline en modulos de negocio

## Politica sobre serializacion JSON

Regla:
- el DAL es responsable de serializar y deserializar campos `*_json`

El codigo de negocio no deberia ir haciendo:
- `json.dumps`
- `json.loads`

por toda la aplicacion.

## Manejo de timestamps

Regla recomendada:
- el DAL escribe timestamps UTC normalizados
- formato ISO 8601 con precision suficiente

No dejar que cada capa los construya a su manera.

## Manejo de errores

La capa DAL deberia distinguir al menos:
- error de integridad
- error de concurrencia
- error de migracion
- error de serializacion
- error de DB ocupada o timeout

Clases de error sugeridas:
- `PersistenceError`
- `ConcurrencyConflictError`
- `MigrationError`
- `SerializationError`

## Concurrencia optimista

La politica recomendada ya definida por revisiones debe vivir en el DAL.

Ejemplo:
- `update_if_revision_matches(...)`

Si no coincide:
- lanzar `ConcurrencyConflictError`

Eso evita que la logica de versionado quede duplicada arriba.

## Integracion recomendada con el codebase actual

## 1. No tocar primero la GUI

La GUI actual es enorme y mezcla muchas responsabilidades.

No empezaria por ahi.

## 2. Punto de entrada recomendado

El primer punto de integracion deberia ser el loop principal de ejecucion
estrategica.

Candidatos naturales del repo actual:
- `main.py`
- la futura capa que reemplace `apply_signal()`

## 3. Evolucion por fases

### Fase 1

Introducir solo:
- bootstrap DB
- `strategy_instances`
- `strategy_state`
- `plans`
- `execution_reports`
- `event_log`

Sin cambiar aun toda la ejecucion.

### Fase 2

Introducir:
- `entry_groups`
- `legs`
- `fills`

### Fase 3

Introducir:
- `pending_orders`
- queries avanzadas
- vistas derivadas

## Estrategia de adopcion incremental

Regla:
- primero persistir sin cambiar demasiado la semantica vieja
- luego cambiar el motor

Motivo:
- reduces riesgo
- ganas observabilidad antes de reescribir la operativa

## Pruebas recomendadas para el DAL

## 1. Tests de migracion

- DB vacia -> aplica todas
- DB parcial -> aplica pendientes
- version repetida -> falla

## 2. Tests de repositorio

- insert y read de cada agregado
- indices y unicidad basica
- serializacion JSON

## 3. Tests de concurrencia

- mismatch de revision
- doble `plan_id`
- lock corto en escrituras concurrentes

## 4. Tests de transaccion

- si falla un paso, rollback completo en DB
- no dejar medias escrituras

## Que no haria en la v1 del DAL

- ORM complejo
- patron generic repository abstracto para todo
- abstraer tanto que el SQL desaparezca

Eso suele empeorar la claridad justo cuando mas importa.

## Decision actual

La propuesta v1 es:
- modulo `src/persistence/`
- runner de migraciones simple
- conexion SQLite configurada en un solo sitio
- repositorios por agregado
- `UnitOfWork` para transacciones
- servicios coordinadores para persistencia de ejecucion y replay
- adopcion incremental empezando por el loop principal y no por la GUI

