# Pre-Implementation: IDataFeed & IHistoricalDataSource Interfaces

**By**: Daniel
**Date**: 2026-04-13
**Task**: TASK-036
**Status**: ready

---

## Formal Problem Statement

**Input**:
- `strategy_runtime.py` (raíz): importa `MetaTrader5 as mt5` al nivel de módulo solo para definir `TIMEFRAME_MAP` (7 constantes enteras). Ninguna función del módulo llama a MT5 directamente.
- `backtesting/runtime.py`: importa `mt5` a nivel de módulo y llama a `mt5.copy_rates_range()` en `_build_market_dataframe()` y a `mt5.symbol_info()` en `BacktestEngine.__init__`. También usa `mt5.TIMEFRAME_*` como claves en `TIMEFRAME_MINUTES`.
- `data_feed.py`: `get_rates_df()` llama a `mt5.copy_rates_from_pos()`. Las demás funciones (`add_source_columns`, `add_baseline_bands`, `add_supertrend`, `add_tci`) son puramente pandas — sin dependencia MT5.

**Output**:
- Protocolo `IDataFeed` (`abc.ABC`) con firma tipada en `src/data/interface.py`: fuente de datos enriquecida para el runtime live
- Protocolo `IHistoricalDataSource` (`abc.ABC`) con firmas tipadas en `src/data/interface.py`: fuente de datos histórica para el backtest engine
- Contratos (no implementación) de `MT5DataFeed`, `DukascopyProvider` y `FileProvider`
- Estructura de `src/data/symbols.json` (registro canónico de símbolos)
- Decisión explícita sobre el import MT5 en `strategy_runtime.py`
- Estructura de caché local por provider
- Spec de cómo `BacktestEngine` recibe `IHistoricalDataSource` por constructor injection
- Spec de cómo `main.py` y `gui_charts.py` reciben `IDataFeed` por parámetro con default MT5

**Constraints**:
- `trading.py` no se toca en este task (cambios a `normalize_volume` quedan en scope de TASK-035)
- `InstrumentInfo` ya definida en `src/broker/interface.py` (TASK-034) — reutilizar, no duplicar
- Python 3.10+; `abc.ABC` + `@abstractmethod`; `Protocol` runtime-checkable como alternativa si se justifica
- El módulo `strategy_runtime.py` es importado tanto por el runtime live como por `backtesting/runtime.py` — cualquier cambio debe ser backward-compatible con el runtime live (que sí tiene MT5)

**Invariants**:
- Los 7 valores enteros de `mt5.TIMEFRAME_*` son constantes públicas estables de la API MT5 (sin cambios en 10+ años): M1=1, M5=5, M15=15, M30=30, H1=16385, H4=16388, D1=16408
- `data_feed.add_source_columns`, `add_baseline_bands`, `add_supertrend`, `add_tci` son funciones puras sobre DataFrames — no necesitan saber el origen de los datos
- El DataFrame retornado por cualquier provider debe tener exactamente las mismas columnas que retorna `mt5.copy_rates_range()` después del procesamiento DataFrame que hace `_build_market_dataframe`

**Clarity**: ✅ clara

---

## Decisión 1: Import MT5 en `strategy_runtime.py`

### Candidatos

#### A — Import guard condicional (try/except)
Wrappear `import MetaTrader5 as mt5` en try/except. En el bloque except, definir las 7 constantes como enteros hardcodeados.

- **Scope de cambio**: solo `strategy_runtime.py` (10 líneas)
- **Riesgo**: ninguno — los valores hardcoded son idénticos a los valores MT5
- **Trade-off**: el guard queda en el código permanentemente hasta que el runtime live también migre

#### B — Abstracción completa de timeframes (eliminar TIMEFRAME_MAP como valores MT5)
Cambiar `TIMEFRAME_MAP` de `{str: mt5_int}` a `{str: str}` (identity) o `{str: int_minutos}`. Eliminar la dependencia del tipo de entero MT5 del contrato del mapa.

- **Scope de cambio**: `strategy_runtime.py` + `backtesting/runtime.py` (TIMEFRAME_MINUTES usa `mt5.TIMEFRAME_*` como claves) + todos los callers que usan `timeframe_value` como entero MT5
- **Riesgo**: `BacktestRequest.timeframe_value` actualmente es `int` y fluye a `MT5DataProvider`; cambiar el tipo requiere coordinar con TASK-037
- **Trade-off**: limpio a largo plazo pero fuera del scope puntual de este task

### Decisión: **Opción A — Import guard condicional**

**Justificación**:
- `strategy_runtime.py` solo usa `mt5` para 7 constantes enteras — ninguna llamada de función. El guard resuelve el problema de importación en entornos sin MT5 con cambio mínimo y riesgo cero.
- La abstracción completa requiere coordinar el tipo de `timeframe_value` (actualmente `int` MT5 en `BacktestRequest`, `BacktestEngine`, `TIMEFRAME_MINUTES`) con los cambios de TASK-037. Hacerlo aquí ampliaría el scope de TASK-036 innecesariamente.
- El guard es reversible: cuando TASK-037 elimine la dependencia MT5 de `backtesting/runtime.py`, el guard en `strategy_runtime.py` puede eliminarse junto con él.

**Pseudocode del guard** (Felix implementa en `strategy_runtime.py`):

```
try:
    import MetaTrader5 as mt5
    _TF_M1  = mt5.TIMEFRAME_M1   # = 1
    _TF_M5  = mt5.TIMEFRAME_M5   # = 5
    _TF_M15 = mt5.TIMEFRAME_M15  # = 15
    _TF_M30 = mt5.TIMEFRAME_M30  # = 30
    _TF_H1  = mt5.TIMEFRAME_H1   # = 16385
    _TF_H4  = mt5.TIMEFRAME_H4   # = 16388
    _TF_D1  = mt5.TIMEFRAME_D1   # = 16408
except ImportError:
    _TF_M1  = 1
    _TF_M5  = 5
    _TF_M15 = 15
    _TF_M30 = 30
    _TF_H1  = 16385
    _TF_H4  = 16388
    _TF_D1  = 16408

TIMEFRAME_MAP = {
    "M1": _TF_M1, "M5": _TF_M5, "M15": _TF_M15, "M30": _TF_M30,
    "H1": _TF_H1, "H4": _TF_H4, "D1": _TF_D1,
}
```

Reemplaza las líneas 9–21 actuales de `strategy_runtime.py`. El resto del módulo no cambia.

---

## Decisión 2: Por qué dos interfaces separadas (IDataFeed vs IHistoricalDataSource)

| Dimensión | IDataFeed (runtime live) | IHistoricalDataSource (backtest) |
|-----------|--------------------------|----------------------------------|
| Pregunta semántica | "Dame las últimas N velas ahora mismo" | "Dame todo el rango [start, end] con warmup" |
| Parámetros clave | `symbol`, `timeframe`, `bars: int` | `symbol`, `timeframe`, `start: datetime`, `end: datetime` |
| Volumen típico | 500 filas siempre | 1,000–200,000+ filas según rango |
| Frecuencia de llamada | Cada `SLEEP_SECONDS` (10s), en loop, en ThreadPoolExecutor × k estrategias | Una vez por ejecución de backtest |
| Requisitos de latencia | < 1s (timing crítico) | Sin límite estricto; puede tardar segundos |
| Estado interno | Stateless (MT5 mantiene el estado) | Stateful (caché, paginación, descarga) |
| Callers actuales | `main.py`, `gui_charts.py` | `backtesting/runtime.py` |

**Conclusión**: Fusionarlas en una sola interfaz crearía un "god interface" donde `MT5BrokerAdapter` implementaría métodos que nunca usa el runtime, y `DukascopyProvider` implementaría un `get_rates_last_n()` que no tiene semántica natural para datos históricos. La separación es el mínimo de complejidad necesario.

---

## Spec: `src/data/interface.py`

### Archivo: `src/data/interface.py`

```
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
import pandas as pd
from src.broker.interface import InstrumentInfo   # reutilizar, no duplicar


class IDataFeed(ABC):
    """
    Fuente de datos para el runtime en vivo.

    Responsabilidad: dado un símbolo y timeframe, retorna un DataFrame ya
    completamente enriquecido — equivalente al resultado de:
        data_feed.get_rates_df() +
        add_source_columns() + add_baseline_bands() + add_supertrend() + add_tci()

    El consumidor (main.py, gui_charts.py) no necesita aplicar ninguna
    transformación adicional; recibe el DataFrame listo para estrategias.
    """

    @abstractmethod
    def get_enriched_df(
        self,
        symbol: str,       # símbolo tal como lo conoce el broker/feed (e.g. "#Germany40")
        timeframe: str,    # "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1"
        bars: int,         # número de velas a obtener (típicamente config.BARS_HISTORY = 500)
    ) -> pd.DataFrame:
        # Retorna DataFrame con columnas mínimas:
        #   time             pd.Timestamp (tz=UTC), ordenado ASC
        #   open, high, low, close, tick_volume  (tipos MT5 habituales)
        #   OHLC4, HLC3, HL2, CLOSE, h_set, l_set  (de add_source_columns)
        #   average, upper, lower, atr              (de add_baseline_bands)
        #   supertrend, supertrend_dir, supertrend_up, supertrend_down  (de add_supertrend)
        #   tci, tci_signal, tci_hist               (de add_tci)
        # Nunca retorna None — lanza RuntimeError si no hay datos.
        ...


class IHistoricalDataSource(ABC):

    @abstractmethod
    def get_rates_df(
        self,
        symbol: str,           # símbolo canónico (e.g. "GER40", "EURUSD")
        timeframe: str,        # "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1"
        start: datetime,       # UTC; incluir warmup (ya calculado por el caller)
        end: datetime,         # UTC; inclusive
    ) -> pd.DataFrame:
        # Retorna DataFrame con columnas:
        #   time       pd.Timestamp (tz=UTC)
        #   open       float64
        #   high       float64
        #   low        float64
        #   close      float64
        #   tick_volume int64  (0 si no disponible)
        #   spread     int64  (0 si no disponible)
        #   real_volume int64  (0 si no disponible)
        # Ordenado por time ASC. Nunca retorna None — lanza RuntimeError si sin datos.
        ...

    @abstractmethod
    def get_instrument_info(
        self,
        symbol: str,           # símbolo canónico
    ) -> Optional[InstrumentInfo]:
        # Retorna InstrumentInfo para el símbolo. None si no conocido.
        # Fuentes: symbols.json (proveedores sin MT5) o MT5 directamente (MT5Provider).
        ...
```

---

## Spec: Contratos de providers concretos

### `MT5DataFeed` (`src/data/mt5_data_feed.py`)

```
import data_feed as _data_feed   # módulo raíz data_feed.py
import config as _config
from src.data.interface import IDataFeed


class MT5DataFeed(IDataFeed):
    """
    Implementación concreta de IDataFeed que envuelve data_feed.py del runtime actual.
    Toda la cadena add_* se aplica internamente; el caller recibe el DataFrame enriquecido.
    Los parámetros de indicadores se reciben en el constructor para no importar config
    desde la interfaz.
    """

    def __init__(
        self,
        source_mode: str,            # config.SOURCE_MODE
        ma_length: int,              # config.MA_LENGTH
        atr_length: int,             # config.ATR_LENGTH
        atr_mult: float,             # config.ATR_MULT
        supertrend_atr_length: int,  # config.SUPERTREND_ATR_LENGTH
        supertrend_mult: float,      # config.SUPERTREND_MULT
        supertrend_source: str,      # config.SUPERTREND_SOURCE
        supertrend_use_hma: bool,    # config.SUPERTREND_USE_HMA
        hma_length: int,             # config.HMA_LENGTH
        tci_fast: int,               # config.TCI_FAST
        tci_slow: int,               # config.TCI_SLOW
        tci_signal: int,             # config.TCI_SIGNAL
    ):
        # guarda todos los parámetros como atributos de instancia
        ...

    def get_enriched_df(self, symbol, timeframe, bars):
        tf_int = TIMEFRAME_INT[timeframe]    # mismo dict que MT5DataProvider
        df = _data_feed.get_rates_df(symbol, tf_int, bars)
        df = _data_feed.add_source_columns(df, self._source_mode)
        df = _data_feed.add_baseline_bands(df, self._ma_length, self._atr_length, self._atr_mult)
        df = _data_feed.add_supertrend(
            df,
            atr_length=self._supertrend_atr_length,
            atr_mult=self._supertrend_mult,
            source_col=self._supertrend_source,
            use_hma=self._supertrend_use_hma,
            hma_length=self._hma_length,
        )
        df = _data_feed.add_tci(
            df,
            fast_length=self._tci_fast,
            slow_length=self._tci_slow,
            signal_length=self._tci_signal,
        )
        return df
```

**Notas críticas para Felix**:
- `MT5DataFeed.__init__` recibe todos los parámetros de indicadores explícitamente — NO importa `config`. El caller (main.py, gui_charts.py) pasa `config.*` al construir la instancia.
- La razón: mantener la misma convención que `MT5BrokerAdapter` (TASK-034 spec); las interfaces no dependen de `config`.
- `TIMEFRAME_INT` se reutiliza del mismo dict ya definido en `mt5_provider.py`; moverlo a `src/data/_timeframes.py` como constante compartida es optativo.

---

### `MT5DataProvider` (`src/data/mt5_provider.py`)

```
import MetaTrader5 as mt5
from src.data.interface import IHistoricalDataSource
from src.broker.interface import InstrumentInfo

TIMEFRAME_INT = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408,
}

class MT5DataProvider(IHistoricalDataSource):

    def get_rates_df(self, symbol, timeframe, start, end):
        tf_int = TIMEFRAME_INT[timeframe]
        # translate canonical symbol → MT5 symbol via symbols.json
        mt5_symbol = _resolve_mt5_symbol(symbol)
        rates = mt5.copy_rates_range(mt5_symbol, tf_int, start, end)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No se pudieron obtener datos para {symbol}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df.sort_values("time").reset_index(drop=True)

    def get_instrument_info(self, symbol):
        mt5_symbol = _resolve_mt5_symbol(symbol)
        info = mt5.symbol_info(mt5_symbol)
        if info is None:
            return None
        # Construir InstrumentInfo igual que MT5BrokerAdapter.get_instrument_info()
        return InstrumentInfo(symbol=symbol, ...)

    def _resolve_mt5_symbol(self, symbol):
        # Lee src/data/symbols.json, devuelve providers["mt5"] para el símbolo canónico
        # Si no encontrado, retorna symbol sin traducir (fallback)
        ...
```

### `DukascopyProvider` (`src/data/dukascopy_provider.py`)

```
class DukascopyProvider(IHistoricalDataSource):

    def __init__(self, cache_dir: str = "cache/dukascopy"):
        self._cache_dir = cache_dir
        self._symbols = _load_symbols_json()   # src/data/symbols.json

    def get_rates_df(self, symbol, timeframe, start, end):
        dukascopy_symbol = self._symbols[symbol]["providers"]["dukascopy"]
        # 1. Determinar meses requeridos en el rango [start, end]
        # 2. Para cada mes:
        #    a. Comprobar si existe cache/<provider>/<symbol>/<timeframe>/<YYYY-MM>.parquet
        #    b. Si existe → cargar desde parquet
        #    c. Si no existe → descargar de Dukascopy API → guardar en parquet → cargar
        # 3. Concatenar todos los meses → filtrar al rango exacto [start, end]
        # 4. Garantizar columnas: time, open, high, low, close, tick_volume, spread, real_volume
        # 5. Retornar DataFrame ordenado por time ASC
        ...

    def get_instrument_info(self, symbol):
        # Lee instrument metadata de symbols.json (tick_size, tick_value, point, digits, ...)
        # Construye y retorna InstrumentInfo. None si símbolo no en symbols.json.
        ...
```

### `FileProvider` (`src/data/file_provider.py`)

```
class FileProvider(IHistoricalDataSource):

    def __init__(self, data_dir: str = "cache/file"):
        self._data_dir = data_dir
        self._symbols = _load_symbols_json()

    def get_rates_df(self, symbol, timeframe, start, end):
        # Busca archivos en: data_dir/<symbol>/<timeframe>/*.parquet o *.csv
        # Carga todos los archivos encontrados → concatena → filtra a [start, end]
        # Lanza RuntimeError si no hay archivos para symbol+timeframe
        ...

    def get_instrument_info(self, symbol):
        # Igual que DukascopyProvider: lee de symbols.json
        ...
```

---

## Spec: `src/data/symbols.json`

Registro canónico de instrumentos. Fuente de verdad para:
1. Traducción de símbolo canónico → símbolo por provider
2. Metadata del instrumento para providers sin MT5 (FileProvider, DukascopyProvider)

```json
{
  "GER40": {
    "description": "German DAX 40 Index",
    "category": "index",
    "providers": {
      "mt5": "#Germany40",
      "dukascopy": "GER40",
      "file": "GER40"
    },
    "instrument": {
      "tick_size": 0.1,
      "tick_value": 1.0,
      "point": 0.1,
      "digits": 1,
      "volume_min": 0.01,
      "volume_max": 100.0,
      "volume_step": 0.01,
      "volume_digits": 2,
      "trade_stops_level": 0,
      "trade_freeze_level": 0,
      "trade_fillings": 1,
      "filling_mode": 1,
      "trade_exemode": 0
    }
  },
  "EURUSD": {
    "description": "Euro / US Dollar",
    "category": "forex",
    "providers": {
      "mt5": "EURUSD",
      "dukascopy": "EURUSD",
      "file": "EURUSD"
    },
    "instrument": {
      "tick_size": 0.00001,
      "tick_value": 1.0,
      "point": 0.00001,
      "digits": 5,
      "volume_min": 0.01,
      "volume_max": 500.0,
      "volume_step": 0.01,
      "volume_digits": 2,
      "trade_stops_level": 0,
      "trade_freeze_level": 0,
      "trade_fillings": 1,
      "filling_mode": 1,
      "trade_exemode": 0
    }
  }
}
```

**Notas**:
- La clave es el nombre canónico del instrumento (usado en `BacktestRequest.symbol` y en todo el sistema post-abstracción)
- `instrument` contiene los campos exactos de `InstrumentInfo` (TASK-034), permitiendo que `FileProvider` y `DukascopyProvider` construyan un `InstrumentInfo` sin MT5
- Los valores de `instrument` son de referencia; `MT5DataProvider` ignora esta sección y obtiene los valores directamente de `mt5.symbol_info()`

---

## Spec: Estructura de caché local

```
cache/
├── dukascopy/
│   └── <canonical_symbol>/
│       └── <timeframe>/
│           └── <YYYY-MM>.parquet      # una partición por mes
├── file/
│   └── <canonical_symbol>/
│       └── <timeframe>/
│           └── <any_name>.parquet     # archivos planos del usuario
│           └── <any_name>.csv
```

**Convención de naming**:
- `cache/dukascopy/GER40/M1/2024-01.parquet` — partición mensual de datos Dukascopy
- `cache/file/GER40/M1/historico_2023.parquet` — datos arbitrarios del usuario

**Schema de cada archivo parquet/CSV** (columnas mínimas requeridas):
```
time          int64 o datetime  (epoch segundos o pd.Timestamp UTC)
open          float64
high          float64
low           float64
close         float64
tick_volume   int64             (puede ser 0)
spread        int64             (puede ser 0)
real_volume   int64             (puede ser 0)
```

`FileProvider` convierte `time` a `pd.Timestamp UTC` al cargar, sin importar si es epoch o datetime.

---

## Spec: Inyección de `IDataFeed` en `main.py` y `gui_charts.py`

### Patrón de inyección

El runtime live no tiene una clase central ("orquestador") como `BacktestEngine`. El acoplamiento a `data_feed.*` está en la función módulo-nivel `_build_market_dataframe()` de `main.py` (líneas 342–360) y en una función análoga dentro de `gui_charts.py`. El patrón de inyección es:

1. **Construir la instancia concreta en el punto de entrada** (`main()`, o en `gui_charts.py` donde arranca el loop de GUI), pasando todos los parámetros de `config.*`.
2. **Pasar la instancia hacia abajo** a `run_bot_loop()` / al loop GUI como parámetro.
3. **Dentro del loop**, llamar `data_feed_impl.get_enriched_df(symbol, timeframe, bars)` en lugar de `_build_market_dataframe()`.

### Firma actualizada de `run_bot_loop` (TASK-037/039 Felix implementa)

```
# ANTES
def run_bot_loop(strategy_entries: list):
    ...
    market_cache[timeframe_value] = _build_market_dataframe(timeframe_value, config.BARS_HISTORY)

# DESPUÉS
def run_bot_loop(strategy_entries: list, data_feed_impl: IDataFeed = None):
    if data_feed_impl is None:
        from src.data.mt5_data_feed import MT5DataFeed
        data_feed_impl = _make_mt5_data_feed()   # helper que lee config.* y construye la instancia
    ...
    market_cache[timeframe_str] = data_feed_impl.get_enriched_df(
        config.SYMBOL, timeframe_str, config.BARS_HISTORY
    )
```

Donde `_make_mt5_data_feed()` es un helper local en `main.py`:

```
def _make_mt5_data_feed():
    from src.data.mt5_data_feed import MT5DataFeed
    return MT5DataFeed(
        source_mode=config.SOURCE_MODE,
        ma_length=config.MA_LENGTH,
        atr_length=config.ATR_LENGTH,
        atr_mult=config.ATR_MULT,
        supertrend_atr_length=getattr(config, "SUPERTREND_ATR_LENGTH", config.ATR_LENGTH),
        supertrend_mult=getattr(config, "SUPERTREND_MULT", 3.0),
        supertrend_source=getattr(config, "SUPERTREND_SOURCE", "close"),
        supertrend_use_hma=getattr(config, "SUPERTREND_USE_HMA", True),
        hma_length=getattr(config, "HMA_LENGTH", 55),
        tci_fast=getattr(config, "TCI_FAST", 9),
        tci_slow=getattr(config, "TCI_SLOW", 21),
        tci_signal=getattr(config, "TCI_SIGNAL", 5),
    )
```

El default `None` → lazy-construye `MT5DataFeed()` dentro de `run_bot_loop` garantiza backward-compatibility: la llamada `run_bot_loop(entries)` desde `main()` no cambia.

### `gui_charts.py` — mismo patrón

`gui_charts.py` tiene su propio loop de refresco que llama una función equivalente a `_build_market_dataframe`. El patrón es idéntico:
- El loop de GUI construye `_make_mt5_data_feed()` una vez al arrancar.
- Lo pasa al loop de refresco como parámetro (o lo guarda como atributo de la clase GUI).
- **Grace deberá reflejar este patrón en la spec GUI** (no está en scope de TASK-037 la implementación GUI).

### Conversión de timeframe

En el loop actual de `main.py`, `timeframe_value` es el entero MT5 (e.g. `1` para M1). `IDataFeed.get_enriched_df` acepta string canónico (`"M1"`). Felix debe:
1. Convertir al construir el cache key: `timeframe_str = runtime_timeframe_label(timeframe_value)` (función ya disponible en `strategy_runtime.py`).
2. Usar `timeframe_str` como clave de `market_cache` en lugar de `timeframe_value` entero.

---

## Spec: Constructor injection en `BacktestEngine`

### `BacktestEngine.__init__` (TASK-037 implementa)

```
# ANTES
class BacktestEngine:
    def __init__(self, request: BacktestRequest):
        self.symbol_info = mt5.symbol_info(self.symbol)    # acoplamiento directo
        self.point = self.symbol_info.point
        self.tick_size = self.symbol_info.trade_tick_size
        self.tick_value = self.symbol_info.trade_tick_value
        self._normalize_volume → llama trading.normalize_volume(lot, self.symbol_info)

# DESPUÉS
class BacktestEngine:
    def __init__(self, request: BacktestRequest, data_source: IHistoricalDataSource):
        self._data_source = data_source
        ...
        instrument_info = data_source.get_instrument_info(self.symbol)
        if instrument_info is None:
            raise RuntimeError(f"No se pudo obtener información del símbolo {self.symbol}")
        self.point     = instrument_info.point
        self.tick_size = instrument_info.tick_size
        self.tick_value = instrument_info.tick_value
        self._instrument_info = instrument_info    # guardado para _normalize_volume
        ...
```

### `_build_market_dataframe` → método de instancia

```
# ANTES (función module-level que llama mt5.copy_rates_range directamente)
def _build_market_dataframe(symbol, timeframe_value, start_date, end_date, warmup_bars):
    rates = mt5.copy_rates_range(symbol, timeframe_value, warmup_start, end_date)
    ...

# DESPUÉS (método de instancia que delega al data_source)
def _build_market_dataframe(self, start_date, end_date, warmup_bars):
    timeframe_minutes = _TIMEFRAME_STR_TO_MINUTES[self.timeframe_label]   # "M1" → 1, etc.
    warmup_start = start_date - timedelta(minutes=warmup_bars * timeframe_minutes)
    df = self._data_source.get_rates_df(
        self.symbol,
        self.timeframe_label,    # string canónico: "M1", "M5", ...
        warmup_start,
        end_date,
    )
    if df is None or df.empty:
        raise RuntimeError(f"No se pudieron obtener datos para {self.symbol}")
    df = df.sort_values("time").reset_index(drop=True)
    df = data_feed.add_source_columns(df, config.SOURCE_MODE)
    df = data_feed.add_baseline_bands(df, config.MA_LENGTH, config.ATR_LENGTH, config.ATR_MULT)
    df = data_feed.add_supertrend(df, ...)
    df = data_feed.add_tci(df, ...)
    return df
```

`_TIMEFRAME_STR_TO_MINUTES` es un dict local en `backtesting/runtime.py`:
```
_TIMEFRAME_STR_TO_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}
```
Reemplaza `TIMEFRAME_MINUTES` (que usaba mt5.TIMEFRAME_* como claves).

### `_normalize_volume` (impacto secundario)

Actualmente: `trading.normalize_volume(lot, self.symbol_info)` donde `symbol_info` es objeto MT5 crudo.

Con abstracción: `trading.normalize_volume(lot, self._instrument_info)`.

TASK-035 actualiza `trading.normalize_volume` para aceptar `InstrumentInfo`. TASK-037 usa esa versión ya actualizada.

### `run_backtest` público (entry point)

```
# ANTES
def run_backtest(request: dict) -> dict:
    engine = BacktestEngine(BacktestRequest.from_dict(request))
    return engine.run()

# DESPUÉS
def run_backtest(request: dict, data_source: IHistoricalDataSource = None) -> dict:
    if data_source is None:
        from src.data.mt5_provider import MT5DataProvider
        data_source = MT5DataProvider()
    engine = BacktestEngine(BacktestRequest.from_dict(request), data_source)
    return engine.run()
```

El default `MT5DataProvider()` garantiza backward-compatibility: los callers existentes (`gui_charts.py`) no necesitan cambios en fase 1.

---

## Scope de TASK-037 (Felix implementa)

1. Crear `src/data/` con `__init__.py` vacío
2. Crear `src/data/interface.py` con `IDataFeed` e `IHistoricalDataSource` según pseudocode de arriba
3. Crear `src/data/symbols.json` con entradas para `GER40` y `EURUSD` como mínimo
4. Crear `src/data/mt5_data_feed.py` con `MT5DataFeed` (envuelve `data_feed.py` + cadena `add_*`)
5. Crear `src/data/mt5_provider.py` con `MT5DataProvider`
6. Crear `src/data/dukascopy_provider.py` con `DukascopyProvider` (esqueleto; descarga real es fuera de scope)
7. Crear `src/data/file_provider.py` con `FileProvider` (soporte parquet + CSV)
8. Aplicar import guard en `strategy_runtime.py` (pseudocode de Decisión 1)
9. Refactorizar `BacktestEngine`: inyección por constructor, `_build_market_dataframe` como método, `_normalize_volume` usando `InstrumentInfo`
10. Actualizar `run_backtest()` con default `MT5DataProvider()`
11. Eliminar `import MetaTrader5 as mt5` de `backtesting/runtime.py` (ya no necesario)
12. Actualizar `main.py`: añadir `_make_mt5_data_feed()`, actualizar `run_bot_loop()` con parámetro `data_feed_impl`

**Lo que NO hace TASK-037**: no implementa la descarga real de Dukascopy; no migra `gui_charts.py` (el loop GUI queda para TASK-039 coordinado con Grace).
