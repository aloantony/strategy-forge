---
title: Glossary
status: draft
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../../../README.md
  - ../../../strategy_runtime.py
  - ../../../src/runtime/
  - ../../../src/persistence/schema.py
---

# Glossary

| Termino | Significado |
| --- | --- |
| Strategy | Modulo Python que recibe un `DataFrame` y devuelve una senal o payload. |
| Strategy key | Identificador interno de estrategia, usado en registry, magic y comentarios. |
| Signal | Valor normalizado: `buy`, `sell` o `none`. |
| Signal payload | Dict con `signal`, `reason` y campos opcionales como `pyramiding`, `atr_value`, `dynamic_sizing`. |
| Closed candle | Ultima vela cerrada; las estrategias deben evitar decidir sobre una vela incompleta. |
| Runtime legacy | Camino que convierte senales directamente en llamadas a `trading.apply_signal`. |
| Runtime v1 | Camino basado en `context`, `state`, `plan`, normalizacion y `ExecutionEngine`. |
| Plan | Decision estructurada de una estrategia v1 con `actions`. |
| Action | Operacion pedida por un plan: abrir, cerrar, reducir, mover SL/TP, etc. |
| Normalized action | Accion validada y resuelta por `PlanInterpreter`. |
| Execution report | Resultado persistido de ejecutar un plan. |
| Entry group | Grupo canonico de entradas relacionadas. |
| Leg | Recurso canonico que representa una posicion o parte de posicion. |
| Fill | Ejecucion real o simulada de apertura/reduccion/cierre. |
| Pending order | Orden pendiente modelada en persistencia. |
| Event log | Registro append-only de eventos relevantes del runtime. |
| Data source | Fuente historica usada por backtesting: MT5, Dukascopy o file provider. |
| Data feed | Fuente live enriquecida para runtime o GUI. |
| Broker adapter | Implementacion de `IBrokerAdapter`; actualmente `MT5BrokerAdapter`. |
| Magic number | Identificador usado por MT5 para agrupar ordenes por estrategia. |
| Strategy Builder | GUI/generador que produce estrategias `.py` y `.json` desde configuracion. |
| Agent | Rol operativo en `agents/`, por ejemplo Daniel, Grace, Felix o Alex. |
| Spec | Documento previo a implementacion que deja decisiones cerradas para un coder. |
| Correction request | Peticion estructurada de un developer para que un agente corrija algo. |

