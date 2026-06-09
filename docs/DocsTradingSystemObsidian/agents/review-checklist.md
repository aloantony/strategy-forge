---
title: Review Checklist
status: draft
audience: developers, agents
last_reviewed: 2026-04-27
sources:
  - ../../../agents/daniel.md
  - ../../../agents/grace.md
  - ../../../agents/felix.md
  - ../../../agents/alex.md
---

# Review Checklist

## Checklist General

- [ ] El cambio responde a una tarea o correccion concreta.
- [ ] El agente esta dentro de su scope.
- [ ] No hay refactors no pedidos.
- [ ] No se revirtieron cambios ajenos.
- [ ] Los archivos tocados coinciden con el scope declarado.
- [ ] Se actualizaron docs si cambio arquitectura, contrato o flujo.
- [ ] Se ejecutaron tests relevantes o se explico por que no.

## Specs

- [ ] La spec deja decisiones cerradas.
- [ ] La spec cita fuentes del repo actual.
- [ ] La spec define archivos o modulos afectados.
- [ ] La spec incluye edge cases relevantes.
- [ ] La spec incluye test plan.

## GUI

- [ ] Grace especifico cambios no triviales antes de Felix.
- [ ] Se leyeron metodos completos afectados.
- [ ] JS embebido usa braces correctos.
- [ ] Payloads complejos cruzan Python/JS con JSON.
- [ ] DOM nuevo es idempotente.
- [ ] Accesos a config usan `getattr`.

## Backend

- [ ] Alex no toco `gui_charts.py`.
- [ ] Nuevas dependencias estan justificadas.
- [ ] Interfaces no cambiaron sin spec.
- [ ] Tests cubren rutas de error y exito.
- [ ] Cambios en backtest no rompen semantica live sin revision.

## Algoritmos

- [ ] Daniel formalizo input/output/constraints si era necesario.
- [ ] Se compararon alternativas.
- [ ] Complejidad y frecuencia de llamada son razonables.
- [ ] Pseudocodigo no deja decisiones abiertas al coder.

## Persistencia

- [ ] Nueva tabla o campo tiene migracion.
- [ ] Repositorios serializan JSON centralmente.
- [ ] Status respeta constraints.
- [ ] Event log conserva trazabilidad.

