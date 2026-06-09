---
title: Correction Request
status: draft
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../../../agents/context-core.md
  - ./routing-guide.md
---

# Correction Request

Usa este formato cuando un developer quiera decirle a los agentes que algo debe corregirse. La meta es que el agente no tenga que adivinar.

## Formato

```markdown
# Correction Request: <titulo corto>

## Contexto
Que se estaba intentando hacer y en que modo: GUI, live, backtest, docs, agente.

## Sintoma
Que ocurre ahora. Incluye error, captura textual, output o comportamiento observable.

## Esperado
Que deberia ocurrir.

## Evidencia
- Archivo:
- Funcion/metodo:
- Linea aproximada:
- Test o comando:
- Datos de entrada:

## Agente recomendado
Daniel / Grace / Felix / Alex / Jarvis / Docs.

## Scope permitido
Archivos o modulos que se pueden tocar.

## Fuera de scope
Que no debe cambiarse.

## Criterio de aceptacion
Como sabremos que esta corregido.
```

## Ejemplo

```markdown
# Correction Request: Backtest ejecuta una vela tarde

## Contexto
Comparando una estrategia simple entre live y backtesting.

## Sintoma
La senal `buy` aparece en la vela cerrada de las 10:00, pero el backtest abre a las 10:02 en M1.

## Esperado
Debe abrir en el `open` de la vela siguiente, 10:01.

## Evidencia
- Archivo: backtesting/runtime.py
- Funcion: BacktestEngine.run_with_df
- Test: tests/test_backtest_runtime.py
- Datos: estrategia dummy con senal fija tras vela 10:00.

## Agente recomendado
Daniel para confirmar semantica; Alex para implementar.

## Scope permitido
backtesting/runtime.py y tests relacionados.

## Fuera de scope
GUI y trading live.

## Criterio de aceptacion
Nuevo test reproduce el caso y pasa; no cambian resultados de casos existentes sin explicacion.
```

## Buenas Practicas

- Pide un comportamiento verificable, no una opinion.
- Incluye el archivo si lo sabes.
- Di que no debe tocarse.
- Si no sabes el agente, usa [routing-guide.md](routing-guide.md).
- Si la correccion cambia arquitectura, exige spec antes de implementacion.

