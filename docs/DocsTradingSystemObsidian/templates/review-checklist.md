---
title: Review Checklist Template
status: draft
audience: developers
last_reviewed: 2026-04-27
---

# Review Checklist: <change>

## Scope

- [ ] El cambio corresponde a la tarea/correccion.
- [ ] El agente esta dentro de su scope.
- [ ] No hay cambios no relacionados.

## Behavior

- [ ] El comportamiento esperado esta descrito.
- [ ] Hay tests o validacion manual.
- [ ] Los casos de error relevantes estan cubiertos.

## Architecture

- [ ] No cambia contratos publicos sin spec.
- [ ] No duplica logica compartida.
- [ ] Actualiza docs si cambia arquitectura o flujo.

## Risk

- [ ] No toca ejecucion real de ordenes sin verificacion.
- [ ] No introduce dependencias innecesarias.
- [ ] No rompe compatibilidad con Obsidian/GitHub/HTML si toca docs.

