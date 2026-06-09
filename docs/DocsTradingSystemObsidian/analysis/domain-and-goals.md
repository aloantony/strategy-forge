---
title: Domain And Goals
status: draft
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../../../README.md
  - ../../../CLAUDE.md
  - ../../../config.py
  - ../../../agents/context-core.md
---

# Domain And Goals

## Dominio

El sistema opera estrategias de trading sobre datos de mercado, principalmente mediante MetaTrader 5. Su dominio combina:

- Trading live con ejecucion de ordenes.
- Backtesting reproducible para evaluar estrategias.
- Construccion de estrategias desde una GUI.
- Persistencia de decisiones y recursos de ejecucion.
- Coordinacion de agentes que especifican, implementan y revisan cambios.

## Actores

| Actor | Necesidad |
| --- | --- |
| Trader | Ejecutar y supervisar estrategias con bajo riesgo operativo. |
| Developer | Entender arquitectura, modificar features y revisar regresiones. |
| Agente planner | Convertir una necesidad en spec segura. |
| Agente coder | Implementar cambios acotados sin redisenar. |
| Agente reviewer | Revisar algoritmo, GUI o backend segun su scope. |
| Broker / MT5 | Proveer datos, metadata de instrumento y ejecucion de ordenes. |
| Data provider historico | Proveer velas para backtesting, actualmente MT5 o Dukascopy. |

## Objetivos Del Sistema

- Ejecutar multiples estrategias enchufables sobre un mismo simbolo.
- Mantener estrategias aisladas del broker, GUI y config global.
- Reutilizar el mismo contrato de estrategia entre live, GUI y backtest.
- Separar progresivamente ejecucion tecnica de decision estrategica mediante runtime v1.
- Persistir planes, reports, legs, fills y eventos para trazabilidad.
- Permitir backtesting desde GUI y CLI con fuentes historicas intercambiables.
- Permitir que los agentes trabajen con handoffs claros y revisables.

## No Objetivos Actuales

- No es una plataforma multi-broker completa.
- No garantiza ejecucion institucional ni baja latencia.
- No simula todavia todos los costes reales de broker en backtest por defecto.
- No convierte automaticamente specs antiguas en codigo.
- No reemplaza el juicio humano sobre riesgo de trading.

## Criterio De Exito

Un developer nuevo debe poder:

1. Identificar por donde entra un flujo live, backtest o GUI.
2. Saber que modulo modificar segun el tipo de cambio.
3. Saber que agente debe recibir una correccion.
4. Validar si una spec o implementacion respeta el diseno actual.
5. Publicar esta documentacion como HTML sin cambiar la forma de escribir los docs.

