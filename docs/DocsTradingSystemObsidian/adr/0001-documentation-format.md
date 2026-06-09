---
title: ADR 0001 Documentation Format
status: accepted
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../README.md
  - ../site-publishing.md
---

# ADR 0001: Documentation Format

## Status

Accepted.

## Context

La documentacion debe servir para:

- Developers que quieren entender analisis y diseno.
- Agentes que necesitan contexto correcto para planificar o implementar.
- Developers que quieren pedir correcciones concretas a agentes.
- Publicacion futura como HTML.

El usuario propuso Mermaid porque renderiza en Obsidian. La investigacion confirmo que Obsidian y GitHub soportan Mermaid en fenced code blocks. Tambien se detecto que Mermaid C4 nativo esta marcado como experimental, asi que no conviene usarlo como formato base para C4.

## Decision

Usar:

- Markdown portable como formato principal.
- Mermaid estable en bloques `mermaid`.
- C4 representado con `flowchart`, no con sintaxis `C4Context`/`C4Container`.
- Frontmatter YAML simple para futura web HTML.
- Enlaces relativos Markdown.
- Plantillas en `docs/templates/`.

Preparar publicacion futura con Material for MkDocs, sin introducir `mkdocs.yml` todavia.

## Consecuencias

Positivas:

- Render inmediato en Obsidian y GitHub.
- Diffs legibles en Git.
- Bajo coste de mantenimiento.
- Facil de publicar como HTML despues.
- Menos riesgo de que los agentes generen sintaxis C4 Mermaid invalida.

Negativas:

- C4 no tendra tooling especializado en v1.
- Diagramas grandes pueden requerir particion manual.
- La consistencia visual dependera de convenciones, no de un modelo central.

## Alternativas Consideradas

| Alternativa | Resultado |
| --- | --- |
| Mermaid C4 nativo | Rechazado por ser experimental. |
| PlantUML | Potente, pero menos directo en Obsidian/GitHub y requiere tooling adicional. |
| Structurizr DSL | Muy bueno para C4 model-as-code, pero agrega Java/Docker/export y friccion inicial. |
| Docusaurus | Valido para HTML, pero introduce Node/React/MDX para una necesidad que MkDocs cubre con menos coste. |

## Regla De Revision

Si los diagramas de arquitectura crecen o empiezan a duplicar demasiadas relaciones, reconsiderar Structurizr DSL como fuente unica y exportar a Mermaid o imagenes.

