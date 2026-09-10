---
title: Risks And Assumptions
status: draft
audience: developers
last_reviewed: 2026-04-27
sources:
  - ../../../backend/core/config.py
  - ../../../backend/main.py
  - ../../../gui_charts.py
  - ../../../backend/application/
  - ../../../backend/brokers/mt5/trading.py
  - ../../../backend/backtesting/runtime.py
---

# Risks And Assumptions

## Riesgos Tecnicos

| Riesgo | Impacto | Mitigacion |
| --- | --- | --- |
| MT5 no conectado o simbolo no visible | No hay datos ni ejecucion. | Validar `mt5` y `symbol_info`; probar primero demo. |
| Divergencia live/backtest | Resultados historicos no replican live. | Mantener `backend/strategy/runtime.py` como capa comun y documentar diferencias. |
| Cambios inseguros en `gui_charts.py` | Rotura silenciosa de JS embebido o threading. | Leer los metodos completos afectados antes de tocarlos; no hacer refactors oportunistas. |
| Proceso de negocio enterrado en GUI | Difícil de probar y corregir por agentes backend. | Extraer validacion/orquestacion a `backend/application/`. |
| Estrategias con efectos secundarios | Bloqueos, ordenes fuera del runtime o dependencias ocultas. | Estrategias aisladas; no importar broker/config/GUI. |
| Persistencia parcialmente fallida | Planes o estados incompletos. | Mantener event log, transactions por `UnitOfWork` y tests de DAL. |
| Mermaid invalido | Documentacion no renderiza. | Usar sintaxis conservadora y validar con Mermaid CLI cuando sea posible. |
| Specs antiguas contradictorias | Agentes implementan contra contexto obsoleto. | Docs deben enlazar a fuentes actuales y marcar fecha de revision. |

## Supuestos Operativos

- El usuario principal ejecuta el bot en Windows con MT5 conectado.
- El simbolo por defecto es `#Germany40`, configurable en [config.py](../../../backend/core/config.py).
- El historial operativo por defecto es `BARS_HISTORY = 500`.
- El loop puede analizar multiples estrategias con `ThreadPoolExecutor`.
- Las estrategias trabajan sobre vela cerrada; el backtest ejecuta en la apertura de la vela siguiente.
- La documentacion se escribira en espanol, manteniendo nombres de codigo en ingles.

## Supuestos De Documentacion

- Markdown es la fuente de verdad.
- Obsidian y GitHub deben renderizar los diagramas sin plugins especiales.
- HTML futuro debe poder generarse desde `docs/` con una herramienta estatica.
- Mermaid C4 nativo no se usara por estar marcado como experimental en la documentacion oficial de Mermaid.

## Riesgos De Trading

Esta documentacion no valida la rentabilidad de ninguna estrategia. Antes de operar en real:

- Probar en cuenta demo.
- Verificar simbolo, lote, stops, horario de mercado y spread.
- Revisar que `MAGIC_NUMBER` o magic por estrategia no colisionen.
- Revisar el comportamiento de cierre y reversals.
- Verificar que el broker permite el filling mode seleccionado.
