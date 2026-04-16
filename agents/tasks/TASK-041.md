# TASK-041: Implementar DukascopyHistoricalDataSource

- **ID**: TASK-041
- **Priority**: P1
- **Status**: done
- **Assigned**: Alex
- **Blocked by**: TASK-037 (debe existir `src/data/interface.py` con `IHistoricalDataSource`)
- **Blocks**: nada

---

## Context slice

- Símbolo DAX en Dukascopy: `deuidxeur`
- Adaptación de schema (1 línea): `df.reset_index().rename(columns={"timestamp": "time"})`
- `dukascopy-python` devuelve: índice `timestamp` (datetime64 UTC), columnas `open/high/low/close/volume` (float64)
- Rate limit: ~5–10 req/seg; ventana de 500 velas M1 ≈ 8 requests — sin problema operacional
- `IHistoricalDataSource` es creada por TASK-037 en `src/data/interface.py`
- Naming: `DukascopyHistoricalDataSource` / `dukascopy_historical_source.py` — sigue el mismo patrón que `MT5HistoricalDataSource` / `mt5_historical_source.py` establecido en TASK-037.
- Felix no modifica `gui_charts.py`, `backtesting/runtime.py`, ni `data_feed.py` en esta tarea.

---

## Description

Implementar `DukascopyHistoricalDataSource(IHistoricalDataSource)` en `src/data/dukascopy_historical_source.py`. Es el adapter real que descarga datos OHLCV de Dukascopy para el DAX (y cualquier símbolo con entrada en `src/data/symbols.json`). Añadir la dependencia a `requirements.txt`. Añadir tests que verifiquen el contrato sin necesidad de MT5 ni conexión de red real.

---

## Technical context

- **Archivos a leer antes de empezar:**
  - `agents/felix.md` — workflow y constraints del rol
  - `agents/specs/TASK-036-data-provider-spec.md` — spec de `IHistoricalDataSource` (interfaz base) y formato de `symbols.json`
  - `agents/reviews/TASK-040-dukascopy-validation.md` — símbolo exacto, shape del DataFrame, adaptación de schema
  - `src/data/interface.py` — (creado por TASK-037) interfaz base a implementar
  - `src/data/symbols.json` — (creado por TASK-037) registro canónico de símbolos; Felix puede necesitar añadir la clave `"dukascopy"` en la entrada de `GER40` si TASK-037 no la incluyó

- **Archivo nuevo a crear:** `src/data/dukascopy_historical_source.py`

- **Archivo a modificar:** `requirements.txt` — añadir línea `dukascopy-python>=4.0.1`

- **Archivo de tests a crear:** `tests/test_dukascopy_historical_source.py`

- **Archivos que NO tocar:** `backtesting/runtime.py`, `data_feed.py`, `gui_charts.py`, `trading.py`, `config.py`, `main.py`

- **Dependencia a añadir:** `dukascopy-python>=4.0.1` (licencia MIT, requiere Python >=3.10)

### Contrato de `IHistoricalDataSource.get_rates_df`

El método debe devolver un `pd.DataFrame` con columnas exactas (según TASK-036):
```
time          pd.Timestamp (tz=UTC)
open          float64
high          float64
low           float64
close         float64
tick_volume   int64  (0 si no disponible — Dukascopy no provee spread)
spread        int64  (0 — Dukascopy no provee este campo)
real_volume   int64  (0 — Dukascopy solo provee volume genérico)
```
Ordenado por `time` ASC. Nunca retorna `None` — lanza `RuntimeError` si no hay datos.

### Adaptación de schema de Dukascopy

`dukascopy-python` devuelve un DataFrame con `timestamp` como índice (no como columna). La adaptación es:

```python
df = df.reset_index().rename(columns={"timestamp": "time"})
```

Tras esta línea, `volume` de Dukascopy debe mapearse a `tick_volume`; `spread` y `real_volume` se rellenan con 0.

### Resolución de símbolo canónico → Dukascopy

Felix debe leer `src/data/symbols.json` (creado por TASK-037) y extraer `providers["dukascopy"]` para el símbolo canónico recibido (e.g. `"GER40"` → `"deuidxeur"`). Si el símbolo canónico no existe en `symbols.json`, lanzar `ValueError` con mensaje claro.

### `get_instrument_info`

Leer los campos de `instrument` en `symbols.json` y construir un `InstrumentInfo` (definido en `src/broker/interface.py`). Retornar `None` si el símbolo no está en `symbols.json`.

---

## Acceptance criteria

- [ ] `src/data/dukascopy_historical_source.py` existe con clase `DukascopyHistoricalDataSource(IHistoricalDataSource)` implementada
- [ ] `requirements.txt` incluye `dukascopy-python>=4.0.1`
- [ ] `DukascopyHistoricalDataSource.get_rates_df()` devuelve DataFrame con columnas `time` (pd.Timestamp UTC), `open`, `high`, `low`, `close`, `tick_volume`, `spread`, `real_volume`
- [ ] `DukascopyHistoricalDataSource.get_instrument_info()` lee de `src/data/symbols.json` y retorna `InstrumentInfo` o `None`
- [ ] Tests en `tests/test_dukascopy_historical_source.py` pasan sin MT5 instalado y sin conexión de red (mockear `dukascopy_python.fetch` para no requerir acceso real en CI)
- [ ] Los tests verifican: columnas correctas, tipos correctos, orden ASC por `time`, que `tick_volume`/`spread`/`real_volume` son int64 con valor ≥ 0
- [ ] `backtesting/runtime.py` no está modificado (verificar con `git diff backtesting/runtime.py`)
- [ ] `data_feed.py` no está modificado (verificar con `git diff data_feed.py`)
- [ ] `gui_charts.py` no está modificado (verificar con `git diff gui_charts.py`)
