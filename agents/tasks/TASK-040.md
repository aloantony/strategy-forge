# TASK-040: Spike de validación de Dukascopy como fuente de datos

- **ID**: TASK-040
- **Priority**: P1
- **Status**: done
- **Assigned**: Daniel
- **Blocked by**: nada
- **Blocks**: TASK-037

## Files to read

- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto; sección de decisiones de fuente de datos

## Description

Spike de validación de Dukascopy como fuente de datos. Verificar manualmente:

1. Que `dukascopy-python` provee datos de DAX (GER.IDX/EUR o equivalente) en M1 para un rango de al menos 2 años
2. Que el shape del DataFrame resultante (columnas time/open/high/low/close/volume) es compatible con el contrato del engine
3. El rate limit de descarga (solicitudes por unidad de tiempo, tamaño máximo por request)
4. Si hay gaps o datos faltantes significativos en el histórico del DAX

Si la validación falla, escalar a Jarvis con alternativas antes de que TASK-037 comience.

## Technical context

- Relevant files: ninguno (investigación/validación externa)
- Esta es una tarea de investigación pura — no escribe código en el repositorio
- `dukascopy-python` es la librería candidata: `pip install dukascopy-python`
- Símbolo canónico interno del proyecto: `GER40` → Dukascopy mapping: `DEU.IDX/EUR` (a confirmar)
- El engine espera columnas: `time` (epoch UTC), `open`, `high`, `low`, `close`, `volume`
- Alternativas a evaluar si Dukascopy falla: Stooq, OANDA histórico, Interactive Brokers TWS histórico

## Output

`agents/reviews/TASK-040-dukascopy-validation.md`

Estructura mínima del reporte:
- Resultado: PASS / FAIL / PARTIAL
- Símbolo encontrado y nombre exacto en Dukascopy
- Rango de datos disponible (fecha más antigua confirmada)
- Shape del DataFrame (columnas, tipos)
- Rate limit observado
- Gaps o anomalías detectadas
- Recomendación: proceder con TASK-037 o escalar a Jarvis con alternativa

## Acceptance criteria

- [ ] Reporte producido en `agents/reviews/TASK-040-dukascopy-validation.md`
- [ ] El reporte confirma (o niega) que DAX M1 está disponible en Dukascopy para al menos 2 años de histórico
- [ ] El reporte documenta el shape exacto del DataFrame resultante
- [ ] El reporte documenta el rate limit (o indica que no se detectó ninguno)
- [ ] El reporte incluye una recomendación explícita: TASK-037 puede proceder, o escalate a Jarvis con alternativas
- [ ] Si el resultado es FAIL o PARTIAL, Daniel escala a Jarvis antes de que TASK-037 sea asignada
