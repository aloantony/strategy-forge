# Pre-Implementation: Exposición de selección de fuente de datos en formulario de backtest

**By**: Daniel
**Date**: 2026-04-15
**Task**: TASK-049
**Status**: ready

---

## Formal Problem Statement

**Input**:
- Formulario de backtest en `gui_charts.py` — actualmente envía al handler Python: `strategy_key`, `symbol` (en formato MT5, e.g. `#Germany40`), `preset`, `start_date`, `end_date`, `initial_balance`.
- `src/data/symbols.json` — registro canónico de 2 entradas (`GER40`, `EURUSD`) con estructura `providers.mt5`, `providers.dukascopy`, `providers.file` e `instrument`.
- `MT5HistoricalDataSource` (`src/data/mt5_historical_source.py`) — requiere MT5 conectado; no acepta parámetros en el constructor; resuelve símbolo canónico → MT5 internamente via `symbols.json`.
- `DukascopyHistoricalDataSource` (`src/data/dukascopy_historical_source.py`) — acepta símbolo **canónico** (e.g. `GER40`); resuelve canónico → ticker Dukascopy (`deuidxeur`) via `symbols.json`; no requiere MT5; lanza `ValueError` si el símbolo no está en `symbols.json` o no tiene entry `dukascopy`.
- `backtesting/runtime.py` — `run_backtest(request: dict, data_source: IHistoricalDataSource = None)` y `run_backtest_comparison(request: dict, data_source: IHistoricalDataSource = None)`. El campo `request["symbol"]` es el símbolo que llega al `BacktestEngine` y que se pasa a `data_source.get_rates_df(symbol, ...)`. Si `data_source is None`, se instancia `MT5HistoricalDataSource()` por defecto.

**Output**:
- Nuevo campo en el formulario de backtest: selector de fuente de datos.
- Nueva función `build_data_source(source_name, symbol_mt5) -> IHistoricalDataSource` en `src/data/factory.py`.
- Lógica de resolución: símbolo GUI (MT5) → símbolo canónico → instancia concreta de `IHistoricalDataSource`.
- `gui_charts.py` instancia el `data_source` correcto y lo pasa a `run_backtest` / `run_backtest_comparison`. No modifica `backtesting/runtime.py`.

**Constraints**:
- El selector debe ser el cambio de formulario más simple posible — un dropdown de dos opciones es suficiente.
- Cuando se selecciona Dukascopy y el símbolo activo no tiene entry en `symbols.json` (o no tiene `providers.dukascopy`), el error debe mostrarse al usuario en el panel de backtest **antes** de lanzar el hilo worker, no como un error en el resultado del backtest.
- El campo `request["symbol"]` que llega a `run_backtest` / `run_backtest_comparison` sigue siendo el símbolo **canónico** cuando `data_source` es Dukascopy, y el símbolo MT5 cuando `data_source` es MT5. El motor de backtest no debe saber ni manejar la diferencia — recibe el símbolo que el `data_source` entiende.
- `factory.py` no importa `config`. Recibe sus parámetros del caller (`gui_charts.py`).
- `DukascopyHistoricalDataSource` ya acepta el símbolo canónico en `get_rates_df`. El factory no necesita resolución adicional para Dukascopy — solo para MT5 (que acepta el ticker MT5 directo, e.g. `#Germany40`).
- `dukascopy_provider.py` y `dukascopy_historical_source.py` coexisten en `src/data/`. El factory usa **`DukascopyHistoricalDataSource`** (el implementado, con descarga real via `dukascopy-python`), no `DukascopyProvider` (esqueleto con `NotImplementedError`).

**Invariants**:
- El símbolo que llega al formulario de backtest es siempre un símbolo en formato MT5 (e.g. `#Germany40`, `EURUSD`). Puede venir de `get_enabled_symbols()` (que devuelve `mt5.symbols_get()`) o de `config.SYMBOL`.
- El símbolo canónico para `GER40` tiene `providers.mt5 = "#Germany40"`, lo que permite la búsqueda inversa MT5 → canónico iterando sobre `symbols.json`.
- `DukascopyHistoricalDataSource.__init__()` no recibe parámetros. Carga `symbols.json` internamente.
- `MT5HistoricalDataSource.__init__()` no recibe parámetros.
- `symbols.json` es cargado una vez al instanciar cada provider — no hay caché a nivel de factory.

**Clarity**: ✅ clara

---

## Candidate Algorithms

Esta spec no es un problema de selección de algoritmo clásico (no hay complejidad O(n) que comparar). El problema es de **diseño de flujo de datos y resolución de símbolos**. Se aplica el marco de Daniel: enumerar los enfoques candidatos para cada sub-problema, seleccionar y justificar.

### Sub-problema 1: UI del selector de fuente

#### Candidato A — Dropdown (`<select>`) con opciones "MT5" y "Dukascopy"
- **Descripción**: un `<select>` con dos `<option>`. Valor por defecto: `"mt5"`. Envía el valor elegido en el payload JSON.
- **Complejidad de implementación**: mínima — Felix añade un elemento HTML y un `onchange` handler, igual que el `symbolSel` existente.
- **Extensibilidad**: añadir `"file"` en el futuro requiere una sola línea HTML.
- **Veredicto**: **seleccionado**

#### Candidato B — Checkbox "Usar Dukascopy"
- **Descripción**: un `<input type="checkbox">`. Si está marcado, fuente = Dukascopy; si no, fuente = MT5.
- **Complejidad de implementación**: equivalente al dropdown.
- **Problema**: no escala a 3+ fuentes. Cuando se añada FileProvider, el checkbox no sirve.
- **Veredicto**: eliminado — no extensible

#### Candidato C — Radio buttons
- **Descripción**: dos `<input type="radio">` en grupo.
- **Complejidad de implementación**: mayor que el dropdown (más HTML, más handlers).
- **Veredicto**: eliminado — mayor complejidad sin beneficio de UX sobre el dropdown en un formulario compacto

---

### Sub-problema 2: Resolución símbolo GUI (MT5) → símbolo canónico

El formulario envía el símbolo en formato MT5 (e.g. `#Germany40`). `DukascopyHistoricalDataSource.get_rates_df` espera el símbolo canónico (e.g. `GER40`). El factory necesita traducir.

#### Candidato A — Búsqueda inversa en `symbols.json` (iteración lineal)
- **Descripción**: iterar sobre las entradas de `symbols.json`, comparar `entry["providers"]["mt5"] == symbol_mt5`. Retornar la clave canónica si se encuentra.
- **Tiempo**: O(k) donde k = número de entradas en `symbols.json` (actualmente 2; previsto < 50 a largo plazo).
- **Espacio**: O(k) para cargar el JSON.
- **Frecuencia**: llamada una vez por ejecución de backtest (no está en ningún loop).
- **Veredicto**: **seleccionado** — con k < 50 y frecuencia una vez por backtest, O(k) es completamente adecuado. El JSON ya es cargado por el provider; cargar una segunda vez en el factory es un costo mínimo.

#### Candidato B — Índice inverso preconstruido (dict `mt5_symbol → canonical`)
- **Descripción**: al importar `factory.py`, construir un dict inverso `{providers.mt5: canonical_key}` a partir de `symbols.json`. Cada lookup es O(1).
- **Tiempo**: O(1) por lookup, O(k) una vez al importar.
- **Problema**: si `symbols.json` se modifica en runtime, el índice queda stale. El JSON tiene 2 entradas hoy; el índice inverso agrega complejidad de inicialización sin beneficio apreciable.
- **Veredicto**: eliminado — over-engineering para k = 2~50 con frecuencia de llamada = una vez por backtest

#### Candidato C — Resolver vía búsqueda directa por clave canónica intentando múltiples formatos
- **Descripción**: intentar primero `symbols[symbol_mt5]` (por si el símbolo ya es canónico), luego búsqueda inversa.
- **Problema**: no resuelve el caso real. El símbolo de la GUI es `#Germany40`, que no es una clave en `symbols.json`. La clave es `GER40`. La búsqueda directa siempre falla para símbolos MT5 con prefijos de broker.
- **Veredicto**: eliminado — no resuelve el caso principal del problema

---

### Sub-problema 3: Dónde instanciar el data source

#### Candidato A — `gui_charts.py` instancia via `build_data_source()`, pasa el objeto a `run_backtest`
- **Descripción**: `_on_backtest_run` y `_on_backtest_compare` llaman a `build_data_source(source_name, symbol_mt5)` antes de crear el hilo worker. El `data_source` resultante se pasa a `_run_backtest_worker` y de ahí a `run_backtest(request, data_source=data_source)`.
- **Ventaja**: la resolución de símbolo y la validación ocurren en el hilo principal (handler), antes de lanzar el thread. Los errores de símbolo no reconocido se capturan y muestran al usuario inmediatamente, sin esperar al resultado del worker.
- **Alineado con**: la decisión pre-acordada en TASK-049 ("quién instancia: gui_charts.py, no backtesting/runtime.py").
- **Veredicto**: **seleccionado**

#### Candidato B — `backtesting/runtime.py` instancia el data source basándose en `data_provider` del request
- **Descripción**: `run_backtest` lee `request["data_provider"]` y construye el provider internamente.
- **Problema**: `backtesting/runtime.py` ya está desacoplado de MT5 y no debe tener lógica de instanciación. El factory debe estar en `src/data/`, no en `backtesting/`. Además, ya está acordado que `run_backtest` recibe `data_source` como parámetro (TASK-036 spec y el código actual lo confirman).
- **Veredicto**: eliminado — viola la arquitectura de abstracción ya establecida

---

## Selected Algorithm

**Winner**: Candidato A para UI (dropdown), Candidato A para resolución de símbolo (búsqueda inversa lineal), Candidato A para instanciación (gui_charts.py via factory).

**Justification**:
- Dropdown: extensible, minimal, coherente con el resto del formulario. Felix puede implementarlo con el mismo patrón que `symbolSel`.
- Búsqueda inversa O(k): con k ≤ 50 entradas y frecuencia = una vez por backtest, la diferencia de O(k) vs O(1) es microscopios. La simplicidad de implementación y mantenimiento supera cualquier ventaja de un índice preconstruido.
- Instanciación en `gui_charts.py`: el error se detecta antes de lanzar el hilo worker, la validación es responsabilidad del formulario, y `backtesting/runtime.py` queda como consumidor puro de `IHistoricalDataSource`.

---

## Pseudocode Spec

### Función: `resolve_canonical_symbol(symbol_mt5: str) -> str | None`

Ubicación: `src/data/factory.py` (función interna del módulo, no parte del API público).

```
function resolve_canonical_symbol(symbol_mt5: str) -> str | None:
    # Carga symbols.json. Retorna None si el archivo no se puede leer.
    symbols = load_symbols_json()   # lee src/data/symbols.json; retorna {} si error

    # Búsqueda directa: el símbolo ya ES la clave canónica (e.g. "EURUSD")
    if symbol_mt5 in symbols:
        return symbol_mt5

    # Búsqueda inversa: iterar, comparar providers.mt5 con symbol_mt5
    for canonical_key, entry in symbols.items():
        mt5_ticker = entry.get("providers", {}).get("mt5", "")
        if mt5_ticker == symbol_mt5:
            return canonical_key

    # No encontrado
    return None
```

Nota: el caso `symbol_mt5 in symbols` maneja símbolos como `EURUSD` donde el ticker MT5 es idéntico a la clave canónica. Evita la búsqueda inversa innecesaria para esos casos.

---

### Función: `build_data_source(source_name: str, symbol_mt5: str) -> IHistoricalDataSource`

Ubicación: `src/data/factory.py` (función pública).

```
function build_data_source(source_name: str, symbol_mt5: str) -> IHistoricalDataSource:
    # source_name: "mt5" | "dukascopy"
    # symbol_mt5: símbolo en formato GUI/MT5 (e.g. "#Germany40", "EURUSD")
    # Retorna instancia concreta de IHistoricalDataSource lista para usar.
    # Lanza ValueError con mensaje claro al usuario si la configuración es inválida.

    if source_name == "mt5":
        # MT5HistoricalDataSource acepta el símbolo MT5 directamente en get_rates_df
        # No necesita validación de symbol aquí — el símbolo llega a MT5 directamente.
        from src.data.mt5_historical_source import MT5HistoricalDataSource
        return MT5HistoricalDataSource()

    elif source_name == "dukascopy":
        # Verificar que dukascopy-python está instalado antes de instanciar
        try:
            from dukascopy_python import fetch as _check
        except ImportError:
            raise ValueError(
                "dukascopy-python no está instalado. "
                "Ejecuta: pip install 'dukascopy-python>=4.0.1'"
            )

        # Resolver símbolo MT5 → canónico
        canonical = resolve_canonical_symbol(symbol_mt5)
        if canonical is None:
            raise ValueError(
                f"El símbolo '{symbol_mt5}' no tiene entrada en symbols.json. "
                "No se puede usar Dukascopy con este símbolo."
            )

        # Verificar que el símbolo canónico tiene provider dukascopy configurado
        symbols = load_symbols_json()
        dk_ticker = symbols[canonical].get("providers", {}).get("dukascopy")
        if not dk_ticker:
            raise ValueError(
                f"El símbolo '{symbol_mt5}' (canónico: '{canonical}') "
                "no tiene proveedor Dukascopy configurado en symbols.json."
            )

        from src.data.dukascopy_historical_source import DukascopyHistoricalDataSource
        return DukascopyHistoricalDataSource()

    else:
        raise ValueError(f"Fuente de datos no reconocida: '{source_name}'. Valores válidos: 'mt5', 'dukascopy'")
```

---

### Función: `resolve_symbol_for_request(source_name: str, symbol_mt5: str) -> str`

Ubicación: `src/data/factory.py` (función pública auxiliar).

Esta función determina qué valor debe ir en `request["symbol"]` para el `BacktestEngine`, dado que cada data source espera el símbolo en un formato diferente.

```
function resolve_symbol_for_request(source_name: str, symbol_mt5: str) -> str:
    # Retorna el símbolo que debe usarse en request["symbol"] para el BacktestEngine.
    # - MT5: usa el símbolo MT5 directamente (MT5HistoricalDataSource lo resuelve internamente)
    # - Dukascopy: usa el símbolo canónico (DukascopyHistoricalDataSource espera canónico)

    if source_name == "mt5":
        return symbol_mt5

    elif source_name == "dukascopy":
        canonical = resolve_canonical_symbol(symbol_mt5)
        if canonical is None:
            # No debería llegar aquí si build_data_source fue llamado primero
            # (que ya validó). Pero por defensividad:
            raise ValueError(
                f"No se pudo resolver símbolo canónico para '{symbol_mt5}'"
            )
        return canonical

    else:
        return symbol_mt5
```

---

### Cambios en `gui_charts.py`: `_on_backtest_run` (Alex implementa en TASK-051)

```
function _on_backtest_run(self, json_str: str):
    # ... (código existente: parse JSON, validar strategy_key, symbol, balance, fechas) ...

    # NUEVO: leer source_name del payload (default "mt5")
    source_name = str(payload.get("data_source") or "mt5").lower()
    if source_name not in ("mt5", "dukascopy"):
        source_name = "mt5"

    # NUEVO: instanciar data source antes de lanzar el hilo
    try:
        data_source = build_data_source(source_name, symbol)
    except ValueError as e:
        self.backtest_state["error"] = str(e)
        self._render_backtest_panel()
        return

    # NUEVO: resolver símbolo para el request (canónico para Dukascopy, MT5 para MT5)
    request_symbol = resolve_symbol_for_request(source_name, symbol)

    # Guardar source_name en el form state para restaurar el selector tras re-render
    self.backtest_state["form"]["data_source"] = source_name

    request = {
        "strategy_key":   entry["key"],
        "strategy_label": entry["label"],
        "module":         entry.get("module_obj"),
        "symbol":         request_symbol,          # MODIFICADO: símbolo resuelto
        "data_provider":  source_name,             # para el resultado del backtest
        "timeframe_value": entry.get("timeframe_value"),
        "start_date":     start_date,
        "end_date":       end_date,
        "initial_balance": initial_balance,
        # ... (resto sin cambios) ...
    }

    self.backtest_thread = threading.Thread(
        target=self._run_backtest_worker,
        args=(request, data_source),    # MODIFICADO: pasar data_source al worker
        daemon=True,
    )
    self.backtest_thread.start()
```

---

### Cambios en `gui_charts.py`: `_run_backtest_worker` (Alex implementa en TASK-051)

```
function _run_backtest_worker(self, request: dict, data_source: IHistoricalDataSource = None):
    # MODIFICADO: recibe data_source como parámetro (antes no lo tenía)
    try:
        result = run_backtest(request, data_source=data_source)
    except Exception as error:
        result = {"status": "error", "error": str(error)}
    # ... (resto sin cambios) ...
```

---

### Cambios en `gui_charts.py`: `_on_backtest_compare` y `_run_backtest_comparison_worker` (Alex implementa en TASK-051)

Mismo patrón que `_on_backtest_run` / `_run_backtest_worker`:

```
function _on_backtest_compare(self, json_str: str):
    # ... (código existente) ...

    source_name = str(payload.get("data_source") or "mt5").lower()
    if source_name not in ("mt5", "dukascopy"):
        source_name = "mt5"

    try:
        data_source = build_data_source(source_name, symbol)
    except ValueError as e:
        self.backtest_state["comparison_error"] = str(e)
        self._render_backtest_comparison_panel()
        return

    request_symbol = resolve_symbol_for_request(source_name, symbol)

    request = {
        "symbol":     request_symbol,    # MODIFICADO
        "data_provider": source_name,
        # ... resto sin cambios ...
    }

    self.comparison_thread = threading.Thread(
        target=self._run_backtest_comparison_worker,
        args=(request, data_source),    # MODIFICADO
        daemon=True,
    )
    self.comparison_thread.start()


function _run_backtest_comparison_worker(self, request: dict, data_source: IHistoricalDataSource = None):
    try:
        result = run_backtest_comparison(request, data_source=data_source)
    except Exception as error:
        result = {"status": "error", "error": str(error)}
    # ... resto sin cambios ...
```

---

## Campos nuevos en el formulario GUI

Grace (TASK-050) y Felix (TASK-052) implementan los cambios de GUI. Esta es la spec exacta de qué campos nuevos se añaden:

### Campo: selector de fuente de datos

| Atributo | Valor |
|----------|-------|
| Tipo HTML | `<select>` |
| ID | `tv-backtest-datasource` |
| Posición | Después del campo "Símbolo", antes del campo "Timeframe" (readonly) |
| Opciones | `<option value="mt5">MT5</option>`, `<option value="dukascopy">Dukascopy</option>` |
| Valor por defecto | `"mt5"` |
| Label | "Fuente de datos" |
| Clase contenedor | `tv-backtest-field` (igual que el resto de campos del formulario) |
| Estado en `backtest_state["form"]` | `"data_source": "mt5"` (string, inicializado a `"mt5"`) |

### Cómo se envía al backend

El payload JSON enviado en `runBtn.onclick` incluye el campo nuevo:

```
const request = {
    strategy_key: ...,
    symbol: ...,
    preset: ...,
    start_date: ...,
    end_date: ...,
    initial_balance: ...,
    data_source: datasourceSel.value || "mt5",   // NUEVO
};
```

El mismo campo se añade al payload de comparación (`backtest_compare`).

### Estado que el formulario debe restaurar al re-render

`state.form.data_source` se guarda en `backtest_state["form"]` al hacer click en "Ejecutar backtest". Al re-renderizar el panel con `window.renderBacktestPanel(payload)`, `datasourceSel.value` se restaura a `state.form.data_source || "mt5"`.

---

## Restricciones de compatibilidad entre fuente y parámetros de backtest

| Restricción | MT5 | Dukascopy |
|-------------|-----|-----------|
| Requiere MT5 conectado | Sí — fallará con `RuntimeError("MetaTrader5 no está disponible")` si MT5 no está instalado/conectado | No — funciona sin MT5 |
| Requiere `dukascopy-python` instalado | No | Sí — `build_data_source` lanza `ValueError` si no está instalado |
| Símbolo debe estar en `symbols.json` | No (fallback: pasa el ticker MT5 tal cual) | Sí — `build_data_source` lanza `ValueError` si el símbolo no tiene entry en `symbols.json` o no tiene `providers.dukascopy` |
| Rango de fechas | Sin restricción conocida (MT5 limita a la historia disponible del broker) | Sin restricción técnica de la librería; Dukascopy tiene datos históricos desde ~2003 para la mayoría de pares. El motor de backtest no impone restricciones de rango. |
| `get_instrument_info` | Requiere MT5 conectado | Lee de `symbols.json`; retorna `None` si el símbolo no tiene `instrument` entry — `BacktestEngine.__init__` lanzará `RuntimeError` en ese caso |
| Spread/slippage real | MT5 puede reportar spread real | Dukascopy no provee spread; siempre 0 en `tick_volume` → parámetros de formulario `spread_points` y `slippage_points` son la única fuente |

**Nota importante sobre `get_instrument_info` con Dukascopy**: `BacktestEngine.__init__` llama a `data_source.get_instrument_info(symbol)`. Con Dukascopy, esto lee `symbols.json`. Si el símbolo canónico no tiene entry `instrument` completa (tick_size, tick_value, point > 0), el engine lanzará `RuntimeError("Symbol X has invalid tick metadata")`. `symbols.json` actualmente tiene entradas válidas para `GER40` y `EURUSD`. Para cualquier símbolo nuevo que se añada a Dukascopy, debe tener la sección `instrument` completa en `symbols.json`.

---

## Quién instancia qué

| Componente | Quién lo instancia | Cuándo |
|------------|-------------------|--------|
| `MT5HistoricalDataSource` | `gui_charts.py` via `build_data_source(...)` | En `_on_backtest_run` / `_on_backtest_compare`, en el handler (hilo principal), antes de lanzar el worker thread |
| `DukascopyHistoricalDataSource` | `gui_charts.py` via `build_data_source(...)` | Ídem — en el handler, antes del worker |
| `build_data_source(...)` | `gui_charts.py` — métodos `_on_backtest_run` y `_on_backtest_compare` | — |
| `BacktestEngine` | `backtesting/runtime.py` — funciones `run_backtest` y `run_backtest_comparison` | Dentro del worker thread — sin cambios |

`backtesting/runtime.py` **no cambia**. Ya tiene la firma correcta `run_backtest(request, data_source=None)`. Si `data_source` se pasa (no `None`), lo usa. El default `MT5HistoricalDataSource()` del runtime sigue siendo el fallback para callers que no pasan `data_source` (e.g. llamadas desde CLI o tests).

---

## División de trabajo entre TASK-050, TASK-051, TASK-052

| Task | Agente | Scope |
|------|--------|-------|
| TASK-050 | Grace | Spec de los cambios en `gui_charts.py`: dónde insertar el `<select>` HTML, cómo modificar `_get_backtest_form_state` para incluir `data_source`, cómo modificar el JS `renderBacktestPanel` para restaurar el valor del selector, insertion points exactos |
| TASK-051 | Alex | Crear `src/data/factory.py` con `build_data_source`, `resolve_canonical_symbol`, `resolve_symbol_for_request`; modificar `_on_backtest_run`, `_run_backtest_worker`, `_on_backtest_compare`, `_run_backtest_comparison_worker` en `gui_charts.py` siguiendo los pseudocode de esta spec |
| TASK-052 | Felix | Implementar los cambios HTML/JS en `gui_charts.py` según la spec de Grace (TASK-050) |

---

## Notas / Ambigüedades

### 1. Dos archivos Dukascopy en `src/data/`

Existen `dukascopy_provider.py` (esqueleto con `NotImplementedError`, clase `DukascopyProvider`) y `dukascopy_historical_source.py` (implementación funcional via `dukascopy-python`, clase `DukascopyHistoricalDataSource`). El factory usa `DukascopyHistoricalDataSource`. El archivo `dukascopy_provider.py` es el esqueleto de la spec TASK-036 que fue superado por la implementación real en TASK-041. **Alex puede ignorar `dukascopy_provider.py` — no se usa en ningún flow activo.**

### 2. `symbols.json` solo tiene 2 entradas

`src/data/symbols.json` tiene entradas para `GER40` y `EURUSD`. Si el usuario tiene el símbolo activo `#Germany40` (DAX) o `EURUSD`, Dukascopy funcionará. Para cualquier otro símbolo MT5 (e.g. `US30`, `XAUUSD`), `build_data_source("dukascopy", symbol)` lanzará `ValueError` y el usuario verá el error antes de que arranque el worker. No hay acción requerida para esta spec — es el comportamiento correcto. La extensión de `symbols.json` es trabajo futuro separado.

### 3. `dukascopy-python` puede no estar instalado

`requirements.txt` puede no incluir `dukascopy-python`. El factory verifica el import antes de instanciar. Si no está instalado, el usuario recibe un mensaje claro. No se bloquea al usuario de usar MT5 si Dukascopy no está disponible.

### 4. `_get_backtest_symbol_options` devuelve símbolos MT5 (no canónicos)

`gui_charts.py:722` — `_get_backtest_symbol_options()` llama a `get_enabled_symbols()` que usa `mt5.symbols_get()`. Si MT5 no está conectado, devuelve `[config.SYMBOL]`. Los símbolos siempre son en formato MT5. El factory siempre recibe símbolos MT5 — esto es un invariant confirmado por el código.

### 5. La comparación de backtests usa el mismo símbolo para todas las estrategias

En `_on_backtest_compare`, hay un único campo `symbol` para todas las estrategias comparadas. La fuente de datos (Dukascopy o MT5) también aplica a todas las estrategias. Esto es coherente — el factory se llama una vez, el `data_source` resultante se comparte entre todos los engines de la comparación (ya que `run_backtest_comparison` usa el mismo `data_source` para todas).

### 6. Backward compatibility del worker thread

`_run_backtest_worker(self, request)` actualmente recibe un solo argumento. Se modifica a `_run_backtest_worker(self, request, data_source=None)`. La llamada desde `threading.Thread(target=..., args=(request, data_source))` es compatible. **No hay otros callers de `_run_backtest_worker` en el codebase** — es un método privado invocado solo desde `_on_backtest_run`. Mismo análisis para `_run_backtest_comparison_worker`.
