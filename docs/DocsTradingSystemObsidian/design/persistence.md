---
title: Persistence Design
status: draft
audience: developers
last_reviewed: 2026-04-27
sources:
  - ../../../backend/persistence/schema.py
  - ../../../backend/persistence/dal.py
  - ../../../backend/runtime/execution_engine.py
  - ../../../backend/runtime/state_store.py
---

# Persistence Design

## Objetivo

Registrar decisiones y ejecuciones de forma auditable sin acoplar el runtime a SQL disperso.

## Unit Of Work

`UnitOfWork` agrupa repositorios y transacciones. El runtime live usa locks alrededor de operaciones SQLite porque comparte conexion global.

## Escrituras Del Runtime

```mermaid
sequenceDiagram
  autonumber
  participant Main as backend.main._run_v1_strategy_cycle
  participant UOW as UnitOfWork
  participant Engine as ExecutionEngine
  participant DB as SQLite

  Main->>UOW: ensure strategy instance
  Main->>UOW: load strategy state
  Main->>UOW: insert plan
  Main->>UOW: append plan_received event
  Main->>Engine: execute_plan
  Engine->>UOW: update plan status
  Engine->>UOW: insert execution_report
  Engine->>UOW: insert action_reports
  Engine->>UOW: create groups, legs, fills
  Engine->>UOW: append events
  Main->>UOW: upsert strategy_state
```

## Recurso Canonico

- `entry_group`: agrupacion de una tesis de entrada.
- `leg`: unidad de posicion gestionada.
- `fill`: evento de ejecucion.
- `pending_order`: orden pendiente.

## Serializacion

Los campos `*_json` se manejan como dict/list en repositorios y se serializan centralmente. No conviene escribir JSON a mano fuera del DAL.

## Evolucion De Schema

Las migraciones viven en `schema.py` como lista ordenada. Para cambios futuros:

1. Anadir nueva migracion con version incremental.
2. Mantener compatibilidad con datos existentes.
3. Actualizar repositorios si cambia forma de escritura/lectura.
4. Anadir test de migracion o DAL.
5. Actualizar [../architecture/persistence.md](../architecture/persistence.md).

## Riesgos

- Los `except Exception: pass` en runtime protegen el loop, pero pueden ocultar fallos de trazabilidad. Si se investiga persistencia, revisar event log y tests.
- Cambios de status deben respetar `CHECK` constraints de SQLite.
- `event_log` debe permanecer robusto y append-only.

