# Plantilla para nuevos agentes

Cuando Jarvis crea un nuevo agente, su archivo `agents/<nombre>.md` debe seguir esta estructura obligatoria. El objetivo es mantener los archivos de rol concisos — cada token que un agente lee de su propio rol file es un token que no puede usar para el trabajo real.

## Estructura obligatoria

```markdown
# <Nombre> — <Rol en una línea>

_Una frase de cuándo invocarlo._

---

## Role

Qué hace. Qué NO hace. Con quién interactúa en el equipo.
Máximo 10 líneas.

---

## What <Nombre> Does NOT Do

Lista de prohibiciones. Máximo 8 items.

---

## Workflow

Pasos numerados. Cada paso: título + 2-4 líneas de descripción.
Sin ejemplos de código inline — los ejemplos van en agents/templates/.

---

## Calibration Notes

Hechos fijos del proyecto que el agente necesita cada vez (tamaños de archivo, patrones de threading, invariantes del sistema).
Sin decisiones históricas ni razonamientos — solo hechos operativos actuales.
```

## Reglas de contenido

1. **Sin plantillas de output inline.** Los formatos de output van en `agents/templates/<nombre>-<tipo>.md`. El workflow solo dice "usa el template en agents/templates/...".

2. **Sin decision logs.** Las decisiones cerradas de sprints anteriores no pertenecen al archivo de rol. Pertenecen a `context.md` mientras son activas, y se eliminan cuando el sprint termina.

3. **Sin ejemplos de código extensos.** Si un patrón necesita un ejemplo de más de 10 líneas, va en `agents/templates/`. El rol file solo referencia el template.

4. **Calibration Notes = solo hechos operativos actuales.** Si un hecho ya no es relevante para el sprint en curso, se elimina. No es un historial.

## Checklist antes de crear un nuevo agente

- [ ] El archivo de rol tiene menos de 150 líneas
- [ ] No contiene bloques de plantilla (markdown con ``` de más de 15 líneas)
- [ ] No contiene decision logs de sprints pasados
- [ ] Si tiene ejemplos de código, son de menos de 10 líneas o están en agents/templates/
- [ ] El workflow referencia templates en lugar de incluirlos inline
