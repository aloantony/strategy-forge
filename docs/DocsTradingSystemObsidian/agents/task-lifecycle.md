---
title: Task Lifecycle
status: draft
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../../../agents/context-core.md
  - ../../../agents/tasks.md
  - ../../../agents/daniel.md
  - ../../../agents/grace.md
  - ../../../agents/felix.md
  - ../../../agents/alex.md
---

# Task Lifecycle

## Flujo Normal

```mermaid
stateDiagram-v2
  [*] --> Intake
  Intake --> Routing
  Routing --> SpecNeeded
  Routing --> DirectImplementation
  SpecNeeded --> DanielSpec: algorithm/backend
  SpecNeeded --> GraceSpec: GUI
  DanielSpec --> BackendImplementation
  GraceSpec --> GUIImplementation
  DirectImplementation --> Implementation
  BackendImplementation --> Verification
  GUIImplementation --> Verification
  Implementation --> Verification
  Verification --> Review
  Review --> Done
  Review --> CorrectionRequested
  CorrectionRequested --> Routing
  Routing --> Blocked: missing info
  Blocked --> Intake
  Done --> [*]
```

## Estados Practicos

| Estado | Significado |
| --- | --- |
| Intake | Humano/Jarvis define necesidad. |
| Routing | Se decide agente y si hace falta spec. |
| Spec | Daniel o Grace cierra decisiones antes de implementar. |
| Implementation | Felix o Alex toca archivos segun scope. |
| Verification | Tests, lectura de diff, validaciones manuales. |
| Review | Humano o agente reviewer detecta riesgos. |
| Correction | Se pide cambio concreto con evidencia. |
| Done | Se cierra tarea y se actualiza indice. |

## Que Debe Ver Un Developer

Antes de aprobar:

- La tarea tiene scope claro.
- La spec existe si era necesaria.
- El agente que implementa esta dentro de su scope.
- El diff no toca archivos no relacionados.
- Los tests o validaciones relevantes se ejecutaron o se explico por que no.
- La documentacion se actualizo si cambio arquitectura o contrato.

## Como Pedir Correccion

Usa [correction-request.md](correction-request.md). Una buena correccion dice:

- Que falla.
- Donde se ve.
- Que se esperaba.
- Que archivo o agente parece responsable.
- Como aceptar el fix.

