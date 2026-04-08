# Esquema Fisico SQLite V1

## Objetivo

Bajar la arquitectura logica a una base SQLite concreta:
- tablas
- columnas
- tipos
- claves
- indices
- restricciones
- transacciones minimas

## Que significa "fisico"

Hasta ahora definiamos:
- entidades logicas
- contratos
- reglas de ownership
- lifecycle

Ahora definimos:
- como se guarda exactamente en SQLite

## Decision principal

La propuesta formal v1 es:
- una unica base `SQLite`
- con tablas canonicas para estado, recursos, planes, reportes y eventos
- con vistas derivadas opcionales por encima

## Parametros SQLite recomendados

Para modo `live` o `demo`:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
```

Para `paper` o `backtest`, puede relajarse:

```sql
PRAGMA synchronous = NORMAL;
```

## Por que esta configuracion

- `foreign_keys = ON`:
  - evita basura relacional
- `WAL`:
  - mejora convivencia entre lectores y escritor
- `FULL`:
  - prioriza durabilidad en operativa real
- `busy_timeout`:
  - evita fallos agresivos por lock corto

## Convenciones de tipos

Reglas v1:

- ids canonicos:
  - `TEXT`
- timestamps UTC:
  - `TEXT` ISO 8601
- revisiones y contadores:
  - `INTEGER`
- volumenes, precios, pnl:
  - `REAL`
- payloads flexibles:
  - `TEXT` con JSON serializado

## Convenciones de naming

Reglas:
- tablas en plural
- ids en singular + `_id`
- timestamps con sufijo `_at`
- payloads JSON con sufijo `_json`

Ejemplos:
- `plan_id`
- `created_at`
- `payload_json`

## Lo que SI sera tabla canonica en v1

Tablas canonicas recomendadas:
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

## Lo que NO sera tabla canonica en v1

No como fuente primaria:
- `position_views`
- `owned_position_views`
- snapshots completas del broker por cada tick

Motivo:
- son derivados o caches
- se pueden reconstruir a partir de recursos y eventos

## 1. `schema_migrations`

Responsabilidad:
- versionar el schema fisico de la DB

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version      INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    applied_at   TEXT NOT NULL
);
```

## 2. `strategy_instances`

Responsabilidad:
- registrar instancias activas o archivadas
- dar identidad estable a todo lo demas

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS strategy_instances (
    instance_id         TEXT PRIMARY KEY,
    strategy_key        TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    status              TEXT NOT NULL
                        CHECK (status IN ('active', 'archived')),
    book_revision       INTEGER NOT NULL DEFAULT 0
                        CHECK (book_revision >= 0),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    archived_at         TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);
```

Indices recomendados:

```sql
CREATE INDEX IF NOT EXISTS idx_strategy_instances_key_symbol
    ON strategy_instances(strategy_key, symbol);

CREATE INDEX IF NOT EXISTS idx_strategy_instances_status
    ON strategy_instances(status);
```

## 3. `symbol_books`

Responsabilidad:
- controlar revision y ownership del libro por simbolo
- especialmente importante en `netting`

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS symbol_books (
    symbol                   TEXT PRIMARY KEY,
    position_mode            TEXT NOT NULL
                             CHECK (position_mode IN ('hedging', 'netting')),
    ownership_mode           TEXT NOT NULL
                             CHECK (ownership_mode IN ('shared', 'single_owner_per_symbol')),
    active_owner_instance_id TEXT,
    book_revision            INTEGER NOT NULL DEFAULT 0
                             CHECK (book_revision >= 0),
    updated_at               TEXT NOT NULL,
    FOREIGN KEY (active_owner_instance_id)
        REFERENCES strategy_instances(instance_id)
);
```

Notas:
- en `hedging`, `ownership_mode` tipico sera `shared`
- en `netting`, por defecto `single_owner_per_symbol`

## 4. `strategy_state`

Responsabilidad:
- guardar el ultimo state canonico por `instance_id`

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS strategy_state (
    instance_id           TEXT PRIMARY KEY,
    strategy_key          TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    schema_version        INTEGER NOT NULL,
    revision              INTEGER NOT NULL
                          CHECK (revision >= 0),
    last_decision_id      TEXT,
    state_json            TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    FOREIGN KEY (instance_id)
        REFERENCES strategy_instances(instance_id)
        ON DELETE CASCADE
);
```

Indice recomendado:

```sql
CREATE INDEX IF NOT EXISTS idx_strategy_state_revision
    ON strategy_state(revision);
```

## 5. `plans`

Responsabilidad:
- guardar el plan original emitido por la estrategia
- servir para idempotencia y correlacion

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS plans (
    plan_id                     TEXT PRIMARY KEY,
    instance_id                 TEXT NOT NULL,
    strategy_key                TEXT NOT NULL,
    symbol                      TEXT NOT NULL,
    iteration_id                TEXT NOT NULL,
    schema_version              INTEGER NOT NULL,
    status                      TEXT NOT NULL
                                CHECK (status IN (
                                    'received',
                                    'validated',
                                    'executing',
                                    'executed',
                                    'partially_executed',
                                    'rejected_structural',
                                    'rejected_technical',
                                    'rejected_broker',
                                    'duplicate_skipped',
                                    'error'
                                )),
    action_count                INTEGER NOT NULL
                                CHECK (action_count >= 0),
    state_revision_before       INTEGER,
    symbol_book_revision_before INTEGER,
    reason                      TEXT NOT NULL,
    plan_json                   TEXT NOT NULL,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL,
    FOREIGN KEY (instance_id)
        REFERENCES strategy_instances(instance_id)
        ON DELETE CASCADE
);
```

Indices recomendados:

```sql
CREATE INDEX IF NOT EXISTS idx_plans_instance_created
    ON plans(instance_id, created_at);

CREATE INDEX IF NOT EXISTS idx_plans_iteration
    ON plans(iteration_id);

CREATE INDEX IF NOT EXISTS idx_plans_status
    ON plans(status);
```

## 6. `execution_reports`

Responsabilidad:
- guardar el resumen final por plan

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS execution_reports (
    report_id                TEXT PRIMARY KEY,
    plan_id                  TEXT NOT NULL UNIQUE,
    instance_id              TEXT NOT NULL,
    strategy_key             TEXT NOT NULL,
    symbol                   TEXT NOT NULL,
    status                   TEXT NOT NULL
                             CHECK (status IN (
                                 'accepted',
                                 'executed',
                                 'partially_executed',
                                 'rejected_structural',
                                 'rejected_technical',
                                 'rejected_broker',
                                 'duplicate_skipped',
                                 'error'
                             )),
    summary                  TEXT NOT NULL,
    previous_state_revision  INTEGER,
    new_state_revision       INTEGER,
    stats_json               TEXT NOT NULL,
    report_json              TEXT NOT NULL,
    created_at               TEXT NOT NULL,
    FOREIGN KEY (plan_id)
        REFERENCES plans(plan_id)
        ON DELETE CASCADE,
    FOREIGN KEY (instance_id)
        REFERENCES strategy_instances(instance_id)
        ON DELETE CASCADE
);
```

Indice recomendado:

```sql
CREATE INDEX IF NOT EXISTS idx_execution_reports_instance_created
    ON execution_reports(instance_id, created_at);
```

## 7. `action_reports`

Responsabilidad:
- guardar una fila por action para consultas rapidas

Nota:
- aunque el `execution_report` completo vive en JSON, esta tabla evita tener que
  parsear JSON para cada consulta operativa

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS action_reports (
    action_report_id      TEXT PRIMARY KEY,
    report_id             TEXT NOT NULL,
    plan_id               TEXT NOT NULL,
    action_id             TEXT NOT NULL,
    action_type           TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    status                TEXT NOT NULL
                          CHECK (status IN (
                              'validated',
                              'executed',
                              'partially_executed',
                              'rejected_technical',
                              'rejected_broker',
                              'skipped_duplicate',
                              'not_supported',
                              'error'
                          )),
    message               TEXT NOT NULL,
    requested_json        TEXT NOT NULL,
    resolved_targets_json TEXT NOT NULL,
    resolved_values_json  TEXT NOT NULL,
    normalization_json    TEXT NOT NULL,
    broker_result_json    TEXT NOT NULL,
    resource_effects_json TEXT NOT NULL,
    timing_json           TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    FOREIGN KEY (report_id)
        REFERENCES execution_reports(report_id)
        ON DELETE CASCADE,
    FOREIGN KEY (plan_id)
        REFERENCES plans(plan_id)
        ON DELETE CASCADE,
    UNIQUE (plan_id, action_id)
);
```

Indices recomendados:

```sql
CREATE INDEX IF NOT EXISTS idx_action_reports_status
    ON action_reports(status);

CREATE INDEX IF NOT EXISTS idx_action_reports_plan
    ON action_reports(plan_id);
```

## 8. `entry_groups`

Responsabilidad:
- agrupar legs relacionadas

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS entry_groups (
    entry_group_id       TEXT PRIMARY KEY,
    instance_id          TEXT NOT NULL,
    strategy_key         TEXT NOT NULL,
    symbol               TEXT NOT NULL,
    side                 TEXT NOT NULL
                         CHECK (side IN ('long', 'short')),
    status               TEXT NOT NULL
                         CHECK (status IN ('open', 'partially_closed', 'closed', 'cancelled')),
    root_leg_id          TEXT,
    created_by_plan_id   TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    closed_at            TEXT,
    tags_json            TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (instance_id)
        REFERENCES strategy_instances(instance_id)
        ON DELETE CASCADE,
    FOREIGN KEY (created_by_plan_id)
        REFERENCES plans(plan_id)
);
```

Indices recomendados:

```sql
CREATE INDEX IF NOT EXISTS idx_entry_groups_instance_status
    ON entry_groups(instance_id, status);

CREATE INDEX IF NOT EXISTS idx_entry_groups_symbol_status
    ON entry_groups(symbol, status);
```

Nota:
- `root_leg_id` se resuelve mejor por actualizacion posterior
- no le pondria FK dura en la v1 para evitar ciclos y rigidez innecesaria

## 9. `legs`

Responsabilidad:
- unidad primaria de exposicion independiente

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS legs (
    leg_id                  TEXT PRIMARY KEY,
    instance_id             TEXT NOT NULL,
    entry_group_id          TEXT NOT NULL,
    strategy_key            TEXT NOT NULL,
    symbol                  TEXT NOT NULL,
    side                    TEXT NOT NULL
                            CHECK (side IN ('long', 'short')),
    status                  TEXT NOT NULL
                            CHECK (status IN ('pending_open', 'open', 'reducing', 'closed', 'cancelled')),
    opened_by_plan_id       TEXT NOT NULL,
    opened_by_action_id     TEXT NOT NULL,
    origin_order_id         TEXT,
    requested_volume        REAL NOT NULL
                            CHECK (requested_volume >= 0),
    opened_volume           REAL NOT NULL
                            CHECK (opened_volume >= 0),
    remaining_volume        REAL NOT NULL
                            CHECK (remaining_volume >= 0),
    avg_entry_price         REAL,
    stop_loss               REAL,
    take_profit             REAL,
    opened_at               TEXT,
    updated_at              TEXT NOT NULL,
    closed_at               TEXT,
    tags_json               TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (instance_id)
        REFERENCES strategy_instances(instance_id)
        ON DELETE CASCADE,
    FOREIGN KEY (entry_group_id)
        REFERENCES entry_groups(entry_group_id)
        ON DELETE CASCADE,
    FOREIGN KEY (opened_by_plan_id)
        REFERENCES plans(plan_id),
    CHECK (remaining_volume <= opened_volume)
);
```

Indices recomendados:

```sql
CREATE INDEX IF NOT EXISTS idx_legs_instance_status
    ON legs(instance_id, status);

CREATE INDEX IF NOT EXISTS idx_legs_group
    ON legs(entry_group_id);

CREATE INDEX IF NOT EXISTS idx_legs_symbol_status
    ON legs(symbol, status);
```

## 10. `pending_orders`

Responsabilidad:
- guardar ordenes pendientes vivas e historicas

Decision v1:
- esta tabla es para pending orders
- no para todas las ordenes de mercado

Las market orders quedan suficientemente cubiertas por:
- `plans`
- `action_reports`
- `fills`
- `event_log`

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS pending_orders (
    order_id               TEXT PRIMARY KEY,
    instance_id            TEXT NOT NULL,
    entry_group_id         TEXT,
    target_leg_id          TEXT,
    strategy_key           TEXT NOT NULL,
    symbol                 TEXT NOT NULL,
    side                   TEXT NOT NULL
                           CHECK (side IN ('long', 'short')),
    order_kind             TEXT NOT NULL
                           CHECK (order_kind IN ('limit', 'stop')),
    status                 TEXT NOT NULL
                           CHECK (status IN ('working', 'partially_filled', 'filled', 'cancelled', 'rejected', 'expired')),
    requested_volume       REAL NOT NULL
                           CHECK (requested_volume >= 0),
    remaining_volume       REAL NOT NULL
                           CHECK (remaining_volume >= 0),
    limit_price            REAL,
    stop_price             REAL,
    stop_loss              REAL,
    take_profit            REAL,
    broker_order_id        TEXT,
    opened_by_plan_id      TEXT NOT NULL,
    opened_by_action_id    TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    closed_at              TEXT,
    spec_json              TEXT NOT NULL,
    tags_json              TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (instance_id)
        REFERENCES strategy_instances(instance_id)
        ON DELETE CASCADE,
    FOREIGN KEY (entry_group_id)
        REFERENCES entry_groups(entry_group_id),
    FOREIGN KEY (target_leg_id)
        REFERENCES legs(leg_id),
    FOREIGN KEY (opened_by_plan_id)
        REFERENCES plans(plan_id),
    CHECK (remaining_volume <= requested_volume)
);
```

Indices recomendados:

```sql
CREATE INDEX IF NOT EXISTS idx_pending_orders_instance_status
    ON pending_orders(instance_id, status);

CREATE INDEX IF NOT EXISTS idx_pending_orders_broker_order_id
    ON pending_orders(broker_order_id);
```

## 11. `fills`

Responsabilidad:
- registrar ejecuciones inmutables

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS fills (
    fill_id               TEXT PRIMARY KEY,
    instance_id           TEXT NOT NULL,
    strategy_key          TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    entry_group_id        TEXT,
    leg_id                TEXT,
    order_id              TEXT,
    side                  TEXT NOT NULL
                          CHECK (side IN ('long', 'short')),
    fill_kind             TEXT NOT NULL
                          CHECK (fill_kind IN ('open', 'reduce', 'close')),
    volume                REAL NOT NULL
                          CHECK (volume > 0),
    price                 REAL NOT NULL
                          CHECK (price > 0),
    commission            REAL NOT NULL DEFAULT 0,
    swap                  REAL NOT NULL DEFAULT 0,
    broker_deal_id        TEXT,
    broker_order_id       TEXT,
    broker_position_id    TEXT,
    occurred_at           TEXT NOT NULL,
    payload_json          TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (instance_id)
        REFERENCES strategy_instances(instance_id)
        ON DELETE CASCADE,
    FOREIGN KEY (entry_group_id)
        REFERENCES entry_groups(entry_group_id),
    FOREIGN KEY (leg_id)
        REFERENCES legs(leg_id),
    FOREIGN KEY (order_id)
        REFERENCES pending_orders(order_id)
);
```

Indices recomendados:

```sql
CREATE INDEX IF NOT EXISTS idx_fills_leg
    ON fills(leg_id);

CREATE INDEX IF NOT EXISTS idx_fills_group
    ON fills(entry_group_id);

CREATE INDEX IF NOT EXISTS idx_fills_broker_deal_id
    ON fills(broker_deal_id);

CREATE INDEX IF NOT EXISTS idx_fills_occurred_at
    ON fills(occurred_at);
```

## 12. `event_log`

Responsabilidad:
- traza canonica append-only

Decision importante:
- `event_log` no debe depender de demasiadas FKs

Motivo:
- algunos eventos existen antes que el recurso
- otros pueden referenciar recursos externos o estados transitorios
- el log no debe romperse por orden de insercion

DDL propuesto:

```sql
CREATE TABLE IF NOT EXISTS event_log (
    event_id              TEXT PRIMARY KEY,
    occurred_at           TEXT NOT NULL,
    event_type            TEXT NOT NULL,
    iteration_id          TEXT,
    mode                  TEXT NOT NULL,
    strategy_key          TEXT,
    instance_id           TEXT,
    symbol                TEXT,
    plan_id               TEXT,
    action_id             TEXT,
    report_id             TEXT,
    entry_group_id        TEXT,
    leg_id                TEXT,
    order_id              TEXT,
    fill_id               TEXT,
    broker_order_id       TEXT,
    broker_position_id    TEXT,
    payload_json          TEXT NOT NULL
);
```

Indices recomendados:

```sql
CREATE INDEX IF NOT EXISTS idx_event_log_occurred_at
    ON event_log(occurred_at);

CREATE INDEX IF NOT EXISTS idx_event_log_plan
    ON event_log(plan_id);

CREATE INDEX IF NOT EXISTS idx_event_log_action
    ON event_log(action_id);

CREATE INDEX IF NOT EXISTS idx_event_log_instance_time
    ON event_log(instance_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_event_log_leg
    ON event_log(leg_id);
```

## Relaciones importantes del schema

Relaciones clave:

- `strategy_instances -> strategy_state`
- `strategy_instances -> plans`
- `strategy_instances -> entry_groups`
- `strategy_instances -> legs`
- `strategy_instances -> pending_orders`
- `strategy_instances -> fills`

- `plans -> execution_reports`
- `plans -> action_reports`
- `plans -> entry_groups`
- `plans -> legs`

- `entry_groups -> legs`
- `pending_orders -> fills`
- `legs -> fills`

## Campos redundantes intencionales

Hay redundancia intencional en columnas como:
- `strategy_key`
- `symbol`
- `instance_id`

Aunque podrian derivarse en algunos casos, se mantienen para:
- queries mas simples
- depuracion mas rapida
- menor necesidad de joins triviales

## Integridad que forzaria en DB

Si la pondria en DB:
- PKs
- FKs principales
- CHECK de estados conocidos
- CHECK basicos de volumen y revisiones

## Integridad que dejaria al motor

La dejaria en aplicacion:
- ownership fino por `instance_id`
- compatibilidad semantica entre `action` y lifecycle
- politicas de `allocation_policy`
- revalidacion contra broker
- reglas avanzadas de `netting`

Motivo:
- demasiada logica de negocio en SQL volveria el sistema rigido

## Transacciones recomendadas

## Limite de atomicidad real

No existe atomicidad total con el broker externo.

La DB puede ser atomica.
El broker es un sistema externo.

Por tanto, la estrategia correcta es:
- transacciones cortas en SQLite
- broker call fuera del tramo mas largo posible
- reconciliacion clara via eventos y reportes

## Patron recomendado de ejecucion

### Fase A. Reserva y validacion local

1. adquirir lock por simbolo en memoria
2. `BEGIN IMMEDIATE`
3. comprobar deduplicacion de `plan_id`
4. leer `symbol_books.book_revision`
5. leer `strategy_state.revision`
6. insertar `plans` con estado `validated` o `executing`
7. insertar eventos iniciales
8. `COMMIT`

### Fase B. Interaccion con broker

1. enviar request al broker
2. recibir respuesta
3. capturar fills o resultado

### Fase C. Persistencia final

1. `BEGIN IMMEDIATE`
2. revalidar que el libro no quedo incompatible
3. persistir cambios en `pending_orders`, `legs`, `entry_groups`, `fills`
4. incrementar `strategy_instances.book_revision`
5. incrementar `symbol_books.book_revision` si cambio el libro del simbolo
6. persistir `strategy_state`
7. persistir `execution_reports` y `action_reports`
8. insertar eventos finales
9. `COMMIT`

## Por que `BEGIN IMMEDIATE`

Porque:
- evita competir tarde por el writer lock
- hace el fallo de concurrencia mas predecible

## Actualizacion de revisiones

Regla recomendada:
- si cambia el libro de una instancia, subir `strategy_instances.book_revision`
- si cambia el libro del simbolo, subir `symbol_books.book_revision`
- si cambia `strategy_state`, subir `strategy_state.revision`

## Consultas operativas importantes

La v1 debe poder responder facilmente a preguntas como:

### Estado actual

- cual es el ultimo `state` de una instancia
- que `legs` siguen abiertas
- que `entry_groups` siguen vivas
- que pending orders siguen working

### Auditoria

- que hizo el `plan_id = X`
- que eventos produjo `action_id = Y`
- que fills pertenecen a `leg_id = Z`
- por que se rechazo una action

### Replay

- reconstruir todos los eventos de una instancia entre dos timestamps

El schema propuesto soporta esas consultas sin bricolaje excesivo.

## Politica sobre JSON

## Donde usaria JSON

- `strategy_state.state_json`
- `plans.plan_json`
- `execution_reports.report_json`
- `action_reports.*_json`
- `pending_orders.spec_json`
- `tags_json`
- `payload_json`

## Donde NO me esconderia solo en JSON

No meteria solo en JSON:
- ids de correlacion
- status
- revisiones
- timestamps de consulta frecuente

Eso debe vivir en columnas normales.

## JSON validation

Si la build de SQLite trae `json_valid`, es recomendable usar checks.
Si no, la validacion queda en capa Python.

Decision v1 pragmatica:
- no depender de `json_valid` para el schema minimo
- validar JSON principalmente en aplicacion

## Politica de borrado

Decision v1:
- no borrar historico operativo de forma agresiva
- archivar o compactar despues

Especialmente no borrar:
- `fills`
- `event_log`
- `plans`
- `execution_reports`

## Politica de snapshots derivadas

Si mas adelante se necesita:
- tablas materializadas para GUI
- snapshots del broker
- caches de `position_view`

deben tratarse como derivados, no como fuente canonica primaria.

## Ejemplo aplicado a tu estrategia

Para `primeraEstrategia.md`, con:
- una entrada inicial
- dos piramides
- SLs por leg
- cierre por leg o por grupo

este schema permite guardar claramente:
- `grp_001` en `entry_groups`
- `leg_001`, `leg_002`, `leg_003` en `legs`
- fills asociados en `fills`
- decisiones emitidas en `plans`
- resultados en `execution_reports` y `action_reports`
- trazabilidad completa en `event_log`

## Decision actual

La propuesta fisica v1 es:
- SQLite con WAL y FKs activas
- tablas canonicas para instancias, state, planes, recursos, reportes y eventos
- ids y status en columnas
- payloads flexibles en JSON
- transacciones cortas y revalidacion alrededor de la llamada al broker
- `event_log` sin sobrecargarlo de FKs para preservar robustez append-only

