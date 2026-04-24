# Pregunta abierta: ¿crear tarea para DukascopyHistoricalSource ahora o más adelante?

**Originada por:** Daniel (TASK-040, spike de validación Dukascopy)
**Dirigida a:** Jarvis
**Fecha:** 2026-04-13

---

## Contexto

TASK-040 confirmó que Dukascopy es una fuente válida para DAX M1 (12+ años de histórico, esquema compatible, rate limit manejable). El review completo está en `agents/reviews/TASK-040-dukascopy-validation.md`.

TASK-037 (Felix) implementa `MT5HistoricalDataSource` — la inyección de la fuente MT5 en `backtesting/runtime.py`. Pero Dukascopy como fuente alternativa requiere un `DukascopyHistoricalSource` adicional, que **no tiene tarea asignada**.

## Pregunta

¿Debe crearse una tarea para implementar `DukascopyHistoricalSource` ahora (dentro del Sprint B) o se deja para un sprint futuro?

## Argumentos para crearlo ahora (Sprint B)

- La validación ya está hecha (TASK-040). El trabajo de investigación no se desperdicia.
- La interfaz `IHistoricalDataSource` que Felix implementa en TASK-037 es exactamente lo que `DukascopyHistoricalSource` necesita implementar. Hacerlo en el mismo sprint garantiza que la interfaz se diseña teniendo en cuenta dos implementaciones concretas, no solo una.
- El adapter en sí es pequeño: `pip install dukascopy-python` + una clase con `fetch_ohlcv(symbol, start, end, timeframe)` + el rename de `timestamp` → `time`. Felix podría implementarlo como subtarea de TASK-037 o como TASK-041.
- Habilitaría correr backtests **sin MT5 instalado** al terminar el Sprint B — que es el objetivo estratégico declarado.

## Argumentos para dejarlo para después

- El Sprint B ya tiene dependencias complejas (TASK-035 → TASK-038, TASK-036 → TASK-037 → TASK-039). Añadir más trabajo al sprint puede comprometer el foco.
- El objetivo inmediato de TASK-037 es desacoplar `backtesting/runtime.py` de MT5. Un `DukascopyHistoricalSource` es un "bonus" — el desacoplamiento funciona igual con un mock en tests.
- Si `dukascopy-python` tiene problemas de instalación en el entorno de CI/Windows, añade una dependencia nueva al proyecto que no ha sido probada aún en el entorno real.

## Información adicional para la decisión

- Adaptación de schema necesaria (del review TASK-040): `df.reset_index().rename(columns={"timestamp": "time"})` — 1 línea.
- El símbolo a usar: `deuidxeur` (constante `INSTRUMENT_INDICES_DEUIDXEUR`).
- Rate limit para ventanas cortas (500 velas M1 ≈ 8 requests): no es un problema operacional.
- La dependencia nueva es: `dukascopy-python>=4.0.1` (MIT, Python >=3.10).
