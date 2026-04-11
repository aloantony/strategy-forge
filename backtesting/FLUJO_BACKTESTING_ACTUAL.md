# Flujo Del Backtesting En La Versión Actual

## Resumen rápido

En la versión actual hay un único motor operativo de backtesting dentro del paquete `backtesting`:

- `backtesting.runtime`: es el motor **actual** que usa la GUI y el que está alineado con el runtime real del bot.

## Mapa de archivos

- [backtesting/runtime.py](./runtime.py)
- [backtesting/cli.py](./cli.py)
- [backtesting/__main__.py](./__main__.py)
- [strategy_runtime.py](../strategy_runtime.py)
- [gui_charts.py](../gui_charts.py)
- [tests/test_backtest_runtime.py](../tests/test_backtest_runtime.py)
- [tests/test_backtesting_cli.py](../tests/test_backtesting_cli.py)

Si solo quieres entender **qué usa hoy la interfaz gráfica**, céntrate en este recorrido:

1. La pestaña `Backtest` de la GUI recoge estrategia, símbolo, rango de fechas y balance inicial.
2. La GUI construye un `request` y llama a `backtesting.run_backtest(...)`.
3. `backtesting.runtime` carga histórico MT5, aplica el pipeline de datos y evalúa la estrategia vela a vela.
4. El motor simula entradas, salidas, reversals, piramidación y cierre forzado al final del rango.
5. Devuelve un `result` con `final_balance`, `total_profit`, `% return`, `closed_trades`, `win_rate`, `max_drawdown` y detalle de `trades`.

## Qué usa la GUI hoy

La pestaña `Backtest` importa directamente:

- `gui_charts.py` -> `from backtesting import run_backtest`

Y el flujo real es:

1. La GUI prepara el formulario y el estado visual.
2. Al pulsar `Ejecutar backtest`, valida fechas, balance, estrategia y símbolo.
3. Arranca un hilo en segundo plano para no bloquear la interfaz.
4. Ese hilo ejecuta `backtesting.runtime.run_backtest(request)`.
5. Al terminar, la GUI pinta el resultado o el error.

Referencias:

- `gui_charts.py::_get_backtest_payload()`
- `gui_charts.py::_on_backtest_run()`
- `gui_charts.py::_run_backtest_worker()`
- `gui_charts.py::window.renderBacktestPanel`

## Entradas del backtest runtime

El runtime trabaja con un `request` normalizado por `BacktestRequest`.

Campos relevantes:

- `strategy_key`
- `strategy_label`
- `module`
- `symbol`
- `timeframe_value`
- `start_date`
- `end_date`
- `initial_balance`
- `warmup_bars`
- `lot`
- `sl_points`
- `tp_points`

La clase `BacktestRequest.from_dict(...)` resuelve defaults y valida:

- que exista `module`
- que el balance inicial sea `> 0`
- que `end_date >= start_date`
- que el `timeframe` quede resuelto

Referencia:

- `backtesting/runtime.py::BacktestRequest`

## Cómo se resuelve la estrategia

El runtime no exige una estrategia especial de backtesting. Usa el mismo contrato que el motor live legado:

- `get_last_signal(df, verbose=False)`
- o `get_last_signal_payload(df, verbose=False)`

Además, si existen, reutiliza:

- `prepare_dataframe(df)`
- `compute_signals(df, enable_signals)`
- `compute_dir1_and_signals(df, enable_signals)`
- `TIMEFRAME`, `STRATEGY_TIMEFRAME` o `TIMEFRAME_STR`

Esto se centraliza en `strategy_runtime.py`, que hoy es la capa común entre live, GUI y backtest.

Qué hace esa capa:

- resuelve el timeframe
- aplica el pipeline de preparación del `DataFrame`
- normaliza el payload de señal
- unifica extras como `pyramiding`, `atr_value`, `dynamic_sizing` y `volume_ratio`

Referencias:

- `strategy_runtime.py::resolve_timeframe_value()`
- `strategy_runtime.py::get_strategy_timeframe()`
- `strategy_runtime.py::apply_strategy_processing()`
- `strategy_runtime.py::normalize_signal_payload()`
- `strategy_runtime.py::get_strategy_signal_payload()`

## Paso 1: carga de mercado y warmup

El runtime no pide solo el rango visible del usuario. Antes añade una **precarga de warmup**:

- calcula cuántas velas extra necesita
- retrocede desde `start_date`
- descarga histórico MT5 con `mt5.copy_rates_range(...)`

Después prepara el `DataFrame` base:

- ordena por tiempo
- convierte `time` a UTC
- añade columnas fuente
- añade baseline bands
- añade supertrend
- añade TCI

Esto permite que la estrategia reciba un contexto parecido al del motor real y no empiece “en frío” justo en el primer candle visible.

Referencia:

- `backtesting/runtime.py::_build_market_dataframe()`

## Paso 2: preparación del DataFrame de estrategia

Una vez cargado el mercado base, el runtime llama a:

- `strategy_runtime.apply_strategy_processing(df, module, enable_signals=...)`

Ese paso deja el `DataFrame` en el estado esperado por la estrategia concreta. Aquí es donde se añaden indicadores y señales propios de cada módulo.

Referencia:

- `backtesting/runtime.py::BacktestEngine.run()`
- `strategy_runtime.py::apply_strategy_processing()`

## Paso 3: cómo se evalúa la señal

La semántica importante de esta versión es:

- la señal se **lee sobre vela cerrada**
- la operación se **ejecuta en el `open` de la vela siguiente**

Para reproducir el comportamiento live, el runtime:

1. toma prefijos crecientes del `DataFrame`
2. evalúa la estrategia sobre ese prefijo
3. guarda la señal como `pending_signal`
4. aplica esa señal en la siguiente vela visible

Además, si hay warmup previo al primer candle visible, el motor calcula también una `pending_signal` inicial para no perder la orden que “ya venía preparada” antes de entrar en el rango del usuario.

Referencia:

- `backtesting/runtime.py::BacktestEngine.run()`

## Paso 4: modos de simulación

La versión actual soporta dos modos.

### Modo estándar

Se usa cuando la señal efectiva es:

- `buy`
- `sell`
- o cuando no se activa un modo avanzado válido

Reglas:

- una sola dirección activa por estrategia
- si llega señal en la misma dirección, no hace nada
- si llega señal contraria, cierra en `open` de la nueva vela con razón `REVERSAL`
- luego abre la nueva posición
- usa `LOT`, `SL_POINTS` y `TP_POINTS`

Referencia:

- `backtesting/runtime.py::_apply_standard_signal()`

### Modo avanzado

Se activa solo si el payload trae:

- `signal == "buy"`
- `pyramiding == True`
- `atr_value > 0`

Reglas:

- solo abre largos
- puede piramidar
- si `dynamic_sizing` está activo y `volume_ratio > 0`, calcula lote dinámico
- si ya hay una posición larga abierta, solo añade una nueva si el precio avanzó `0.5 * ATR` desde la última entrada
- antes de abrir, verifica el riesgo agregado con `trading.check_aggregate_risk(...)`
- el `SL` queda en `entry - ATR`
- el `TP` queda en `entry + 2 * ATR`

Referencia:

- `backtesting/runtime.py::_open_advanced_buy()`

### Fallback de modo avanzado a estándar

Si la estrategia devuelve un payload “avanzado” pero incompleto, el runtime no fuerza ese modo. Por ejemplo:

- `pyramiding=True` pero `atr_value <= 0`

En ese caso cae al flujo estándar.

Referencia:

- `backtesting/runtime.py::_apply_pending_signal()`

## Paso 5: gestión de salidas

En cada vela el runtime revisa posiciones abiertas:

- comprueba `SL`
- comprueba `TP`
- si se toca ambos en la misma vela, en esta versión manda `SL`

Esa prioridad es deliberadamente conservadora.

Cuando el rango termina:

- si aún quedan posiciones abiertas, se cierran al último `close`
- el motivo del cierre es `END_OF_RANGE`
- esos cierres se marcan como `forced_close=True`

Referencias:

- `backtesting/runtime.py::_check_sl_tp_hit()`
- `backtesting/runtime.py::_process_candle_exits()`
- `backtesting/runtime.py::_close_all_positions()`
- `backtesting/runtime.py::BacktestEngine.run()`

## Paso 6: equity, drawdown y resultado final

Durante la simulación, el runtime va marcando equity sobre el `close` de cada vela:

- `balance`
- `equity`
- floating P&L de posiciones abiertas

Con eso calcula:

- `final_balance`
- `total_profit`
- `total_return_pct`
- `closed_trades`
- `winning_trades`
- `losing_trades`
- `win_rate`
- `max_drawdown`

El resultado final es un `dict` listo para GUI o CLI.

Referencias:

- `backtesting/runtime.py::_mark_equity()`
- `backtesting/runtime.py::_build_success_result()`
- `backtesting/runtime.py::run_backtest()`

## Flujo desde la GUI

La GUI sigue este recorrido:

1. construye las opciones de estrategia, símbolo, presets y formulario
2. muestra la pestaña `Backtest`
3. al enviar, valida:
   - estrategia
   - símbolo
   - balance inicial
   - rango de fechas
4. crea el `request`
5. lanza un hilo
6. recibe `result`
7. vuelve a pintar:
   - estado `running`
   - error inline
   - tarjetas de métricas

Importante:

- el backtest está aislado del motor live
- no cambia `current_strategy_key`
- no toca posiciones reales
- no cambia el símbolo operativo del bot

Referencias:

- `gui_charts.py::_get_backtest_strategy_options()`
- `gui_charts.py::_get_backtest_symbol_options()`
- `gui_charts.py::_get_backtest_preset_ranges()`
- `gui_charts.py::_get_backtest_payload()`
- `gui_charts.py::_on_backtest_run()`
- `gui_charts.py::_run_backtest_worker()`

## Flujo desde CLI

La CLI del paquete se ejecuta así:

```bash
python -m backtesting --help
```

El comando operativo actual es:

### `python -m backtesting runtime`

Usa el motor actual:

- resuelve el módulo de estrategia
- resuelve el timeframe
- crea el `request`
- inicializa MT5
- valida símbolo
- ejecuta `backtesting.runtime.run_backtest(...)`
- imprime el resultado como JSON

Referencia:

- `backtesting/cli.py::_run_runtime()`

## Qué devuelve hoy el runtime

Campos principales del `result`:

- `status`
- `error`
- `strategy_key`
- `strategy_label`
- `symbol`
- `timeframe`
- `start_date`
- `end_date`
- `initial_balance`
- `final_balance`
- `total_profit`
- `total_return_pct`
- `closed_trades`
- `winning_trades`
- `losing_trades`
- `win_rate`
- `max_drawdown`
- `trades`

Referencia:

- `backtesting/runtime.py::_build_success_result()`

## Motor de referencia

El motor que hay que tomar como referencia funcional actual es `runtime` porque:

- está conectado a la GUI
- comparte contrato con el runtime live
- entiende payloads avanzados
- reproduce señal en vela cerrada y ejecución en vela siguiente

## Limitaciones de la versión actual

Esta versión asume:

- sin spread simulado
- sin slippage
- sin comisiones
- propiedades de símbolo tomadas del MT5 actual
- prioridad conservadora de `SL` sobre `TP` cuando ambos saltan en la misma vela

También conviene tener presente que:

- el modo avanzado solo opera largos
- el payload avanzado depende de que la estrategia exponga bien `pyramiding`, `atr_value`, `dynamic_sizing` y `volume_ratio`

## Dónde mirar si algo falla

Guía rápida de depuración:

- falla al pulsar el botón en GUI:
  - `gui_charts.py::_on_backtest_run()`
- el request parece correcto pero la estrategia no responde:
  - `strategy_runtime.py::get_strategy_signal_payload()`
- faltan columnas o indicadores:
  - `strategy_runtime.py::apply_strategy_processing()`
- no hay velas o el histórico sale vacío:
  - `backtesting/runtime.py::_build_market_dataframe()`
- la entrada o salida no coincide con lo esperado:
  - `backtesting/runtime.py::_apply_standard_signal()`
  - `backtesting/runtime.py::_open_advanced_buy()`
  - `backtesting/runtime.py::_check_sl_tp_hit()`
- el resultado agregado no cuadra:
  - `backtesting/runtime.py::_mark_equity()`
  - `backtesting/runtime.py::_build_success_result()`

## Tests que cubren este flujo

Los tests más útiles para entender el comportamiento actual son:

- `tests/test_backtest_runtime.py`
- `tests/test_backtesting_cli.py`

Cubren:

- normalización de payload
- modo estándar con reversión
- modo avanzado con piramidación y sizing dinámico
- fallback de avanzado a estándar
- routing del CLI a `runtime`
