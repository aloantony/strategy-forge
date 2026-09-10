---
title: Trading Agent Developer Docs
status: draft
audience: developers
last_reviewed: 2026-04-27
---

# Trading Agent Developer Docs

Esta carpeta documenta el analisis, la arquitectura y el diseno del sistema. Esta escrita como Markdown portable: se lee igual en GitHub, en Obsidian y como sitio estatico.

## Como Usar Esta Documentacion

- Para entender el sistema en 15 minutos: empieza por [00-system-map.md](00-system-map.md).
- Para entender por que existe cada parte: lee [analysis/domain-and-goals.md](analysis/domain-and-goals.md) y [analysis/requirements.md](analysis/requirements.md).
- Para ver arquitectura y diagramas: entra en [architecture/overview.md](architecture/overview.md) y [architecture/c4.md](architecture/c4.md).
- Para implementar o revisar cambios: usa los documentos de [design/](design/).
- Para reportar una discrepancia entre docs y codigo: usa [templates/correction-request.md](templates/correction-request.md).
- Para publicar esto como HTML mas adelante: revisa [site-publishing.md](site-publishing.md).

## Indice

| Area | Documento | Uso |
| --- | --- | --- |
| Mapa | [00-system-map.md](00-system-map.md) | Vista rapida de modulos, flujos y fuentes de verdad. |
| Analisis | [analysis/domain-and-goals.md](analysis/domain-and-goals.md) | Dominio, objetivos, actores y contexto. |
| Analisis | [analysis/requirements.md](analysis/requirements.md) | Capacidades actuales y restricciones. |
| Analisis | [analysis/risks-and-assumptions.md](analysis/risks-and-assumptions.md) | Riesgos tecnicos y supuestos de diseno. |
| Analisis | [analysis/glossary.md](analysis/glossary.md) | Vocabulario comun para humans y agentes. |
| Arquitectura | [architecture/overview.md](architecture/overview.md) | Capas, responsabilidades y flujos principales. |
| Arquitectura | [architecture/application-services.md](architecture/application-services.md) | Servicios reutilizables fuera de la GUI. |
| Arquitectura | [architecture/c4.md](architecture/c4.md) | Diagramas C4 en Mermaid portable. |
| Arquitectura | [architecture/runtime.md](architecture/runtime.md) | Runtime live, modo legacy y modo v1. |
| Arquitectura | [architecture/data-and-broker.md](architecture/data-and-broker.md) | Proveedores de datos y broker adapter. |
| Arquitectura | [architecture/persistence.md](architecture/persistence.md) | SQLite, repositorios y modelo canonico. |
| Arquitectura | [architecture/backtesting.md](architecture/backtesting.md) | Arquitectura del backtesting actual. |
| Arquitectura | [architecture/deployment.md](architecture/deployment.md) | Entorno Windows/MT5, Python y datos locales. |
| Diseno | [design/live-runtime.md](design/live-runtime.md) | Diseno detallado del loop live. |
| Diseno | [design/gui.md](design/gui.md) | Diseno de GUI y zonas de riesgo. |
| Diseno | [design/strategy-system.md](design/strategy-system.md) | Contrato de estrategias y registry. |
| Diseno | [design/strategy-builder.md](design/strategy-builder.md) | Generador de estrategias. |
| Diseno | [design/backtesting.md](design/backtesting.md) | Semantica de simulacion y resultados. |
| Diseno | [design/broker-data-adapters.md](design/broker-data-adapters.md) | Interfaces y adaptadores. |
| Diseno | [design/persistence.md](design/persistence.md) | Persistencia v1 y recursos canonicos. |
| ADR | [adr/0001-documentation-format.md](adr/0001-documentation-format.md) | Decision del formato documental. |
| ADR | [adr/0002-application-services.md](adr/0002-application-services.md) | Decision de extraer procesos de la GUI. |
| Templates | [templates/technical-page.md](templates/technical-page.md) | Plantilla para nuevas paginas tecnicas. |
| Templates | [templates/correction-request.md](templates/correction-request.md) | Plantilla para reportar discrepancias. |
| Templates | [templates/review-checklist.md](templates/review-checklist.md) | Checklist reutilizable. |

## Convenciones

- Formato principal: Markdown portable con frontmatter YAML simple.
- Diagramas: Mermaid dentro de fenced code blocks `mermaid`.
- Compatibilidad objetivo: Obsidian ahora, GitHub ahora, HTML estatico despues.
- No usar Mermaid C4 experimental; los C4 se representan con `flowchart`.
- Todo documento debe citar los archivos fuente revisados.

## Fuentes Principales Del Repo

- [README.md](../../README.md)
- [CLAUDE.md](../../CLAUDE.md)
- [backend/core/config.py](../../backend/core/config.py)
- [backend/main.py](../../backend/main.py)
- [backend/strategy/runtime.py](../../backend/strategy/runtime.py)
- [backend/backtesting/](../../backend/backtesting/)
- [backend/strategy_builder/](../../backend/strategy_builder/)
- [server/](../../server/)
- [frontend/](../../frontend/)
- [gui_charts.py](../../gui_charts.py)
