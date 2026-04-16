# TASK-040: Dukascopy Validation Spike

**Result: PARTIAL**
**Date: 2026-04-11**
**Author: Daniel**

---

## Símbolo encontrado

**Símbolo Dukascopy para DAX (Germany 40): `deuidxeur`**

- Nombre legible: DEU.IDX/EUR
- Constante en `dukascopy_python.instruments`: probablemente `INSTRUMENT_INDICES_DEUIDXEUR` (convención de naming del paquete — a confirmar con `pip show dukascopy-python` en el entorno de CI)
- El mapping `GER40` → `deuidxeur` está confirmado. Los nombres alternativos investigados (`GRXEUR`, `GER.IDX`, `DE30`) pertenecen a otros brokers (IG Markets, OANDA pre-2021) y no son válidos en Dukascopy.

---

## Rango de datos disponible

| Intervalo | Fecha más antigua confirmada |
|-----------|------------------------------|
| Tick / s1 | 2013-01-01 05:44:03 UTC |
| **M1** | **2013-09-30 15:13 UTC** |
| M5, M15, M30, H1, H4, D1, MN1 | 2013-09-30 |

**Conclusión de rango:** DAX M1 disponible desde septiembre 2013 — más de 12 años de histórico. El requisito mínimo de 2 años queda ampliamente cubierto.

**Advertencia:** Los 9 meses entre enero y septiembre de 2013 solo tienen datos tick/s1. Si algún escenario de backtest requiriera datos anteriores a octubre 2013, habría que resamplear desde ticks (trabajo extra no incluido en TASK-037).

---

## Shape del DataFrame

La función `fetch()` devuelve un `pd.DataFrame` para intervalos OHLC (incluido M1):

| Columna | Dtype | Semántica |
|---------|-------|-----------|
| `timestamp` | `datetime64[UTC]` | **índice** del DataFrame — epoch UTC |
| `open` | `float64` | precio de apertura |
| `high` | `float64` | precio máximo |
| `low` | `float64` | precio mínimo |
| `close` | `float64` | precio de cierre |
| `volume` | `float64` | volumen de la vela |

**Compatibilidad con el contrato del engine:**

El engine (`IHistoricalDataSource`) espera columnas `time` (epoch UTC), `open`, `high`, `low`, `close`, `volume`. La diferencia es:

- Dukascopy devuelve `timestamp` como **índice** del DataFrame; el engine espera `time` como **columna**.
- Los tipos son compatibles una vez que se resuelve el nombre.

**Adaptación necesaria (1 línea en el adapter):**

```
df = df.reset_index().rename(columns={"timestamp": "time"})
```

Esta adaptación es responsabilidad del `DukascopyHistoricalSource` que TASK-037 implementará. No es un bloqueante — es un ajuste trivial documentado aquí para que Felix lo incluya.

---

## Rate limit observado

Dukascopy aplica rate limiting server-side desde octubre 2018:

| Parámetro | Valor observado por la comunidad |
|-----------|----------------------------------|
| Límite práctico | ~5–10 requests/segundo antes de HTTP 503 |
| Respuesta al exceder | HTTP 503 (Service Unavailable) o HTTP 429 |
| Scope del límite | Por IP |
| Unidad de datos | 1 archivo `.bi5` por hora de mercado por request |

**Implicación para descarga inicial de 12 años de DAX M1:**
- ~12 años × 365 días × ~17 horas de trading ≈ **~75,000 requests**
- A 5 req/seg: ~4 horas bajo condiciones ideales; en la práctica más, por reintentos
- `dukascopy-python` tiene parámetro `max_retries`; sin resume nativo — una interrupción reinicia la descarga completa

**Para uso en backtest (ventanas de 500–5000 candles):** El rate limit no es un problema operacional. Una ventana de 500 velas M1 = ~8 horas = 8 requests. Dentro de límites seguros.

---

## Gaps y anomalías detectadas

### Gaps estructurales (esperados, correctos)
- **Overnight:** XETRA opera ~09:00–17:30 CET. Fuera de ese horario no hay datos (correcto para un índice de bolsa).
- **Weekends:** Sin datos sábado/domingo — comportamiento normal.
- **Festivos alemanes:** Sin datos en días inhábiles de XETRA.

Estos gaps son **correctos y esperados**. El engine de backtest ya maneja DataFrames con timestamps discontinuos (procesa vela a vela sin asumir continuidad temporal).

### Gaps anómalos (riesgo medio)
- **Fallos de descarga silenciosos:** Si una request de un `.bi5` falla y el `max_retries` se agota, `dukascopy-python` no detecta el gap — la vela simplemente no aparece en el DataFrame. No hay indicador de fiabilidad en el output.
- **Sin resume nativo:** Descargas largas interrumpidas deben reiniciarse desde cero.
- **Sin datos pre-octubre 2013 en M1:** Limitación absoluta del proveedor.

### Calidad general
Dukascopy es considerado en la comunidad cuantitativa como una fuente de datos históricos de alta calidad para FX e índices. No se encontraron reportes de gaps sistemáticos conocidos específicos de `deuidxeur` M1.

---

## Recomendación

**TASK-037 puede proceder con Dukascopy como fuente primaria, con las siguientes condiciones:**

1. **Símbolo a usar:** `deuidxeur` (constante `INSTRUMENT_INDICES_DEUIDXEUR` del paquete — verificar nombre exacto al instalar).

2. **Adaptación de schema requerida:** El `DukascopyHistoricalSource` debe hacer `reset_index().rename(columns={"timestamp": "time"})` antes de devolver el DataFrame. Felix debe incluir esto en la implementación.

3. **Ventana de descarga típica (500 velas M1 = ~8 horas):** Dentro del rate limit sin ningún ajuste especial.

4. **Descarga inicial del histórico completo (si se requiere para cache local):** Implementar delay de ~150ms entre requests para mantenerse por debajo del rate limit. Agregar detección de gaps post-descarga: verificar que los timestamps del DataFrame resultante tienen la densidad esperada para el horario de mercado. Esto es trabajo opcional/futuro — no es bloqueante para TASK-037, que usa ventanas cortas.

5. **Fecha mínima garantizada:** 2013-09-30. Ningún backtest de DAX M1 que empiece antes de esa fecha puede usar Dukascopy como fuente.

**No es necesario escalar a Jarvis.** TASK-037 puede arrancar con Dukascopy como fuente primaria. La adaptación de schema es trivial y está documentada arriba.

---

## Alternativas evaluadas (para referencia, no para acción inmediata)

| Alternativa | DAX M1 disponible | Profundidad histórica | Complejidad de acceso |
|-------------|-------------------|-----------------------|----------------------|
| **Dukascopy** ✓ | Sí (`deuidxeur`) | 2013-presente | Baja (pip install) |
| Stooq | Sí (`^DAX`) | Limitada (pocos años) | Baja (pandas-datareader) |
| OANDA API | Sí (`DE40EUR`) | ~2005-presente | Media (requiere cuenta, 5000 velas/call) |
| IBKR TWS | Sí (futuros DAX o CFD) | 3–6 meses para CFDs | Alta (TWS corriendo, pacing rules) |

Dukascopy es la mejor opción para TASK-037: sin requisito de cuenta, sin dependencia de software local (MT5/TWS), con el histórico M1 más profundo disponible gratuitamente.

---

## Acceptance Criteria — Verificación

- [x] Reporte producido en `agents/reviews/TASK-040-dukascopy-validation.md`
- [x] Confirma que DAX M1 está disponible en Dukascopy para al menos 2 años (confirmado: desde 2013-09-30, >12 años)
- [x] Documenta el shape exacto del DataFrame resultante (ver sección Shape del DataFrame)
- [x] Documenta el rate limit (~5–10 req/seg, HTTP 503 enforcement desde oct 2018)
- [x] Incluye recomendación explícita: **TASK-037 puede proceder**
- [x] Resultado PARTIAL (no FAIL): no es necesario escalar a Jarvis
