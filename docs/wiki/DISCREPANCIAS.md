# Reporte de discrepancias — reconstrucción de la wiki desde código

Este documento registra las correcciones aplicadas al reconstruir la wiki **analizando el código
fuente** (ignorando `docs/DocsTradingSystemObsidian/`). Cada entrada cita el archivo de código que la
justifica. La versión anterior se apoyaba en los docs Obsidian (estado *draft*) y arrastraba estos
desajustes.

## Correcciones de contenido

| # | Tema | Antes (doc-derivado) | Real (verificado en código) | Fuente |
|---|------|----------------------|------------------------------|--------|
| 1 | Métodos de la GUI | Se citaban `refresh_data`, `update_chart_data`, `run_backtest_single`, `run_comparison`, `toggle_bot`, `bot_loop_worker` | Reales: `run`, `start_bot`, `stop_bot`, `bot_loop`, `_toggle_strategy_run`, `_render_backtest_panel`, `_on_backtest_run`, `_run_backtest_worker`, `_on_backtest_compare`, `_init_strategy_registry`, `_set_strategy_enabled`, `toggle_indicator` | `gui_charts.py` |
| 2 | Espera del loop | `SLEEP_SECONDS` (10 s) como intervalo del loop principal | `run_bot_loop` usa `timeframe_to_seconds(min_timeframe)` (p.ej. 60 s en M1); `SLEEP_SECONDS` no se usa ahí | `main.py:866-867` |
| 3 | Comparación de backtest | Clave de resultados ambigua | La comparación devuelve la clave **`strategies`** | `backtesting/runtime.py:806-814` |
| 4 | Costes en el CLI | `spread/slippage/commission` listados como argumentos del CLI | Existen en `BacktestRequest` pero el CLI **no** los expone | `backtesting/cli.py:79-104` |
| 5 | `--warmup-bars` | "≥ 500" sin más | Default del CLI = `0`; el motor aplica `max(BARS_HISTORY, 500)` = 500 | `backtesting/cli.py:95`, `backtesting/runtime.py:57-58` |
| 6 | Estrategias parametrizables | No documentado | `PARAMS` (`{type, default, min, max, label}`) + `<módulo>.params.json` + kwarg `params` | `main.py:201-311` |
| 7 | Tipos de acción del runtime v1 | Lista parcial | 9 tipos reales en `SUPPORTED_ACTION_TYPES` | `src/runtime/plan_interpreter.py:189-199` |
| 8 | Repos del `UnitOfWork` | Lista aproximada | 11 repos reales (instances, symbol_books, strategy_state, plans, execution_reports, action_reports, entry_groups, legs, fills, pending_orders, event_log) | `src/persistence/dal.py:733-743` |
| 9 | `decode_trade_comment` | Atribuido a `comment.py` | Vive en `trading.py` (que re-exporta `build_trade_comment` de `comment.py`) | `trading.py:23-121` |
| 10 | Riesgo agregado / lote dinámico | "3%" sin verificar | Confirmado `AGGREGATE_RISK_LIMIT = 0.03` (3%); `calculate_dynamic_lot` topa al 1% (`min(volume_ratio·0.005, 0.01)`) | `trading.py:804, 821` |
| 11 | Fábrica de datos | Implicaba MT5/Dukascopy/File en la fábrica | `build_data_source` solo crea `mt5`/`dukascopy`; `FileProvider` existe pero no está cableado | `src/data/factory.py:88-152` |
| 12 | `scripts/debug.py` | No documentado | Runner de depuración (`datasource`, `backtest`, `factory`) | `scripts/debug.py` |
| 13 | Ticker Dukascopy de GER40 | Genérico | Canónico `GER40` → Dukascopy `E_DAAX`, MT5 `#Germany40` | `src/data/symbols.json` |
| 14 | Esquema de persistencia | Tablas aproximadas | 12 migraciones reales; PRAGMAs WAL/FK/FULL | `src/persistence/schema.py` |

## Cambios de estructura (reconstrucción desde 0)

La estructura anterior (11 páginas) se reorganizó para reflejar los subsistemas reales del código
(16 páginas):

- `datos-brokers.html` → se dividió en **`datos.html`** y **`broker-ordenes.html`**.
- `runtime.html` → se dividió en **`runtime-live.html`**, **`runtime-v1.html`** y **`persistencia.html`**.
- Se extrajeron **`configuracion.html`** (referencia de `config.py`) y **`strategy-builder.html`**
  (antes embebido en estrategias) como páginas propias.
- Diseño e implementación de `assets/style.css` y `assets/wiki.js` rehechos desde 0.

Archivos eliminados por quedar huérfanos: `runtime.html`, `datos-brokers.html`.

## Trazabilidad

Cada página termina con un pie **"Fuente (código)"** que enumera los `.py` de los que sale su
contenido. No se usó ningún material de `docs/DocsTradingSystemObsidian/`, `.claude/`, `agents/` ni
`CLAUDE.md`.
