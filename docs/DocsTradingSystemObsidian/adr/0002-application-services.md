---
title: ADR 0002 Application Services
status: accepted
audience: developers
last_reviewed: 2026-04-27
sources:
  - ../../../gui_charts.py
  - ../../../backend/application/backtest_service.py
  - ../architecture/application-services.md
---

# ADR 0002: Application Services

## Status

Accepted.

## Context

`gui_charts.py` ha acumulado responsabilidades de presentacion y proceso: backtesting, registry, workers, Strategy Builder y bot loop. Esto hace que los procesos sean dificiles de probar fuera de la GUI y aumenta el riesgo de romper JS/threading al tocar logica de negocio.

## Decision

Introducir `backend/application/` como capa de servicios reutilizables por GUI, CLI y tests. La GUI captura intencion del usuario y renderiza estado; los servicios validan, construyen requests, resuelven dependencias y llaman a runtimes/adapters.

El primer servicio implementado es `BacktestService`.

## Consecuencias

Positivas:

- Backtesting se puede probar sin GUI.
- La GUI reduce logica de proceso.
- CLI y GUI pueden converger sobre servicios compartidos.
- La frontera es explicita: la logica de proceso vive en `backend/application/`, la GUI solo presenta estado y captura intencion.

Negativas:

- Durante la transicion habra duplicacion parcial.
- Extraer el live loop requerira cuidado por callbacks, threads y estado visual.

## Regla

No anadir nueva orquestacion de proceso a `gui_charts.py` si puede vivir en `backend/application/`.
