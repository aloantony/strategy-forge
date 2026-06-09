---
title: Routing Guide
status: draft
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../../../agents/context-core.md
  - ../../../agents/daniel.md
  - ../../../agents/grace.md
  - ../../../agents/felix.md
  - ../../../agents/alex.md
---

# Routing Guide

## Tabla De Decision

| Problema | Agente recomendado | Motivo |
| --- | --- | --- |
| Indicador incorrecto, calculo vectorial, complejidad, rendimiento. | Daniel primero. | Debe elegir algoritmo o revisar implementacion. |
| Cambio no trivial en `gui_charts.py`. | Grace primero, Felix despues. | Grace define insertion points e invariantes; Felix implementa. |
| CSS/label puntual en GUI. | Felix directo. | Si el edit site es unico y claro. |
| Nueva orquestacion de proceso desde GUI. | Daniel/Alex primero; Grace/Felix solo para wiring visual. | Debe vivir en `src/application/`, no directamente en GUI. |
| Backtesting runtime, datasource, CLI o tests backend. | Daniel si hay decision; Alex implementa. | Backend coder es Alex. |
| Nuevo adapter MT5 concreto o bug en adapter. | Alex. | Scope backend concreto. |
| Cambios en `IBrokerAdapter` o interfaz compartida. | Daniel primero. | Es contrato arquitectonico. |
| Cambios en docs de agentes o routing. | Jarvis/humano. | Afecta protocolo de equipo. |
| Persistencia, schema o DAL. | Daniel si cambia modelo; Alex implementa. | Riesgo de contrato y migracion. |
| Strategy Builder GUI. | Grace primero, Felix despues. | Toca GUI y JS/Python bridge. |
| Strategy Builder generator. | Daniel si cambia modelo; Alex si backend. | Generacion y validacion son backend. |

## Correcciones Frecuentes

| Sintoma | Ruta |
| --- | --- |
| Mermaid no renderiza. | Docs owner o developer; no hace falta Daniel/Grace salvo que cambie arquitectura. |
| Backtest difiere de live. | Daniel para analizar semantica; Alex implementa fix. |
| Bot abre orden duplicada. | Daniel para decision de logica; Alex si backend, Felix si solo UI muestra mal. |
| Bot no muestra estado en GUI. | Grace/Felix. |
| Estrategia generada no importa. | Daniel o Alex segun si es modelo/generador; Felix solo si el bug esta en formulario GUI. |
| Error en `symbols.json` o Dukascopy. | Alex. |
| Documento contradice codigo. | Corregir docs con evidencia; si revela bug real, enrutar segun modulo. |

## Regla De Oro

Si la correccion requiere decidir "que algoritmo, contrato o arquitectura debe existir", empieza por un agente de spec/review. Si solo requiere traducir una decision ya cerrada a codigo, va al coder correspondiente.
