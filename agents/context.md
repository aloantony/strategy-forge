# Project Context

_Last updated by Jarvis: 2026-04-15 (sprint Dukascopy-in-Backtest-GUI agregado TASK-049 a TASK-052; Known Issues limpiados)_

---

## File Hygiene Rules (Jarvis enforces these at every sprint boundary)

These rules exist to prevent token bloat across all agent files. Violating them means every future agent pays a tax for information they don't need.

### context.md
- **When a sprint ends**: remove its decision log, task order list, and any "recommended structure" sections. Keep only facts that are still operationally relevant.
- **Never add**: git log summaries, historical decision rationales for closed decisions, or detailed sprint retrospectives.
- **Current Goals** section: describes only the active sprint. Previous sprints get one line in a "Completed sprints" summary, then nothing.

### Agent role files (daniel.md, grace.md, felix.md, and any future agents)
- **No output templates inline**. Templates live in `agents/templates/`. Role files reference them with one line.
- **No decision logs**. Closed decisions from past sprints are not preserved in role files.
- **No code examples longer than 10 lines**. Longer examples go in `agents/templates/`.
- **Target size**: under 150 lines per role file.
- When creating a new agent, follow `agents/templates/new-agent.md`.

### agents/tasks/
- Active task files (`agents/tasks/TASK-XXX.md`) are the source of truth for task detail.
- `agents/tasks.md` is the compact index only — one table row per task.
- When a task is `done`, its file stays in `agents/tasks/` as a record but is not read by any agent unless explicitly referenced.

---

## Escalation Protocol

**If you have any implementation doubt, ambiguity, or design question while executing a task — stop and escalate to Jarvis. Do not resolve it unilaterally.**

- Write your question clearly in a new file: `agents/questions/<TASK-ID>-<short-slug>.md`
- Update your task Status in `agents/tasks.md` AND your task file (`agents/tasks/<TASK-ID>.md`) to `blocked`, and add a `Blocked by: open question — see agents/questions/<file>` note
- Jarvis will review the question with the user and update `context.md` or the task file with the resolution before you continue

**If you suspect you are missing information to complete your task** — for example, a referenced spec file does not exist yet, a source file contains something unexpected, or a decision required by your task has not been made — you must:
1. Stop immediately. Do not proceed with assumptions.
2. Tell the user directly in your terminal output what is missing and why it blocks you.
3. Ask the user explicitly for permission or the missing information before continuing.

This applies to all agents (Daniel, Grace, Felix, Alex, and any future agents). When in doubt, escalate — never assume.

---

## Agent Team

| Agent | Role | Definition |
|-------|------|-----------|
| **Jarvis** | Project manager — maintains this file and `tasks.md`; briefs agents before sprints | _(configured as Claude Code agent type `jarvis`)_ |
| **Daniel** | Algorithm specialist — pre-implementation algorithm selection (primary) and post-implementation review; enumerates candidates, selects and justifies the winner, produces pseudocode spec the coding agent implements verbatim; flags unclear problem statements to Jarvis before any algorithm work begins. **Jarvis must route through Daniel** for: (1) any backtesting feature work, (2) any new algorithm or indicator implementation | `agents/daniel.md` |
| **Grace** | GUI architect — pre-implementation planning specialist for `gui_charts.py`; maps safe insertion points, defines the threading zone for each change, documents JS/Python interaction patterns, and writes the change spec that Felix implements. **Jarvis must route through Grace** for: (1) any new UI panel, tab, or major section, (2) any `chart.run_script()` JS injection change, (3) any method addition/removal on `TradingBotGUI`, (4) any change touching the bot loop or threading, (5) backtest GUI integration | `agents/grace.md` |
| **Felix** | GUI coder — implements changes to `gui_charts.py` following Grace's spec (spec-driven mode) or direct task descriptions (direct mode for single-site cosmetic edits). Enforces established coding patterns: IIFE wrappers, JSON payload crossing, callback-queue threading, `getattr(config, ...)` access. Does not make architectural decisions | `agents/felix.md` |
| **Alex** | Backend coder — implements non-GUI, non-algorithm work: data layer, broker adapters, runtime wiring, `src/` modules, `backtesting/` internals, tests. Does not touch `gui_charts.py` (Felix/Grace scope). Does not do algorithm selection (Daniel scope) | `agents/alex.md` |

---

## Project

**trading-agent** is a MetaTrader 5 trading bot with pluggable strategies and a TradingView-style GUI. Language: Python. The **only** entry point for users is `gui_charts.py` — all interaction happens through the graphical interface.

### What this project is

- Live trading engine supporting multiple strategies running concurrently on one or more symbols via MT5
- TradingView-style GUI (lightweight_charts + pywebview) for all user interaction: enable/disable strategies, monitor positions, view candles and indicator overlays, and performance metrics
- Backtesting engine (`backtesting/runtime.py`) — already integrated in the GUI and used by the Backtest tab

### What this project is NOT

- Not a console/headless tool (main.py is a secondary headless runner; the GUI is the product)
- Not an HTTP server or webhook system (feedback_server.py is out of scope and will be deleted)
- Not a cTrader integration — MT5 only for now (broker abstraction will enable others in the future)

---

## Vision estrategica (decisiones del 2026-04-11)

**Supersistema v1 (`src/`) es la direccion definitiva.** No es experimental. Es el runtime futuro tanto de `main.py` (headless) como de `gui_charts.py` (GUI). La integracion plena es la meta del sprint de Broker Abstraction (TASK-034 a TASK-039).

**La abstraccion de broker es prioridad inmediata.** El objetivo es que el sistema pueda ejecutarse con cualquier broker sin acoplamientos duros a MT5. La vision es: crear estrategia -> testear (backtest sin MT5 instalado) -> correr en cualquier broker. El sprint de Broker Abstraction materializa esto mediante `IBrokerAdapter`, `MT5BrokerAdapter`, `IDataFeed` e `IHistoricalDataSource`.

---

## Current Goals

**Sprint activo: GUI Polish** (TASK-045 a TASK-048) — todos `todo`, ninguno iniciado. Mejorar la calidad visual e interactiva del GUI sin cambiar la paleta de colores ni la arquitectura de threading:

1. **TASK-045 (Grace)** — Spec completa del sprint: inventario de botones interactivos, cambio quirúrgico del tab switcher (Opción B fade), spinner en botón de backtest, arquitectura del sistema de toast notifications, e insertion points exactos para Felix
2. **TASK-046 (Felix)** — Scroll fix directo: `overflow-y: auto` + scrollbar webkit en `.tv-backtest-panel` y verificar `#tv-strategy-panel` — no depende de TASK-045
3. **TASK-047 (Felix)** — Micro-interacciones y animaciones: transitions CSS, scale en `:active`, hover box-shadow, tab fade-in, spinner — depende de TASK-045
4. **TASK-048 (Felix)** — Toast notifications: HTML container, CSS animaciones, JS `window.tvShowToast()`, Python `show_toast()` thread-safe, integración en 3 puntos del bot-loop — depende de TASK-045

Decisiones tomadas en el plan del sprint:
- Fade de tabs: Opción B (JS mínimo con `requestAnimationFrame` + CSS transition)
- Scroll fix routing: directo a Felix (cambio CSS localizado, sin spec de Grace)
- Spinner en botón de backtest: incluido en TASK-047
- Toast eventos: los 3 (trade abierto, trade cerrado, señal detectada)
- Indicador deslizante de tab y flash de señal en fila: NOT incluidos en este sprint

**Siguiente sprint: Dukascopy-in-Backtest-GUI** (TASK-049 a TASK-052) — todos `todo`. Exponer la selección de fuente de datos (MT5 vs Dukascopy) en el formulario de backtest del GUI:

1. **TASK-049 (Daniel)** — Spec: cómo exponer la selección de fuente de datos, qué parámetros requiere cada fuente, mapeo de símbolo canónico
2. **TASK-050 (Grace)** — Spec GUI: selector de fuente de datos en el formulario de backtest de `gui_charts.py`
3. **TASK-051 (Alex)** — Wiring: conectar la fuente seleccionada a la llamada de `backtesting/runtime.py` en `gui_charts.py`
4. **TASK-052 (Felix)** — Implementación GUI: spec de Grace en `gui_charts.py`

---

## Active Configuration (config.py)

- Symbol: `#Germany40` (DAX Spot CFD on FxPro — prefix varies by broker, do not hardcode new prefixes)
- Lot: `0.01`
- SL / TP: `300` / `500` points
- `STRATEGY_RUNTIME_MODE = "v1_only"` — supersistema v1 ya activo en `main.py`
- `PERSISTENCE_ENABLED = True`, `PLAN_EXECUTOR_ENABLED = True`, `CANONICAL_RESOURCES_ENABLED = True`
- Loop interval: `10s`
- Max strategy workers: `8`
- Analysis timeout: `15s`

---

## Architecture

```
MT5 Connection (mt5_connection.py)
    |
gui_charts.py  <->  main.py (trading loop, strategy runner)
                       |- data_feed.py       -> OHLCV + derived columns
                       |- strategies/        -> pluggable modules (ThreadPoolExecutor)
                       |- trading.py         -> order placement via apply_signal()
                       `- src/               -> supersistema v1 (runtime, persistence, broker abstraction)
```

### Supersistema v1 (`src/`) — estado actual

- `src/runtime/adapter.py` — `LegacyStrategyAdapter`: envuelve modulos legacy al contrato v1 `decide(context, state)`
- `src/runtime/execution_engine.py` — `ExecutionEngine`: ejecuta planes normalizados; actualmente acoplado a `trading_module` concreto (a resolver en TASK-035, completado)
- `src/runtime/plan_interpreter.py` — interpreta planes v1
- `src/runtime/context_builder.py` — construye el contexto de decision
- `src/runtime/state_store.py` — persiste estado de estrategia por instancia
- `src/persistence/` — SQLite + migraciones + DAL
- `src/data/interface.py` — `IDataFeed`, `IHistoricalDataSource` (creados en TASK-037)
- `src/data/mt5_data_feed.py` — `MT5DataFeed(IDataFeed)` (creado en TASK-037)
- `src/data/mt5_historical_source.py` — `MT5HistoricalDataSource(IHistoricalDataSource)` (creado en TASK-037)
- `src/data/dukascopy_historical_source.py` — `DukascopyHistoricalDataSource(IHistoricalDataSource)` (creado en TASK-041)
- `strategy_runtime.py` (raiz) — helpers compartidos runtime/backtest; import de mt5 aislado (resuelto en TASK-037)

### Broker Abstraction — Arquitectura objetivo (TASK-034 a TASK-039, completo)

```
IBrokerAdapter (src/broker/interface.py)
    `-- MT5BrokerAdapter (src/broker/mt5_adapter.py) -> trading.py

IDataFeed (src/data/interface.py)
    `-- MT5DataFeed (src/data/mt5_data_feed.py) -> data_feed.py

IHistoricalDataSource (src/data/interface.py)
    `-- MT5HistoricalDataSource (src/data/mt5_historical_source.py)
    `-- DukascopyHistoricalDataSource (src/data/dukascopy_historical_source.py)
```

`backtesting/runtime.py` recibe `data_source: IHistoricalDataSource` inyectado — ya no llama `mt5.copy_rates_range()` directamente.

### Key file sizes / risk notes

- `gui_charts.py` is **~6613 lines** — all edits must be **targeted and surgical**; route non-trivial changes through Grace before assigning to Felix
- `backtesting/runtime.py` is the current backtest engine used by the GUI
- `trading.py`: `apply_signal()` is the sole public API for order execution; `_close_position()` and `_send_order()` are private helpers
- `data_feed.py`: still active as a legacy wrapper; `MT5DataFeed` wraps it — do not modify

### GUI architecture (`gui_charts.py`)

The file contains a single class `TradingBotGUI` with ~90 methods. No sub-classes, no mixins. The major logical sections are:

1. **Init and chart setup** (`__init__` lines ~84-270, `setup_topbar` ~1591)
2. **Strategy registry** (`_init_strategy_registry` ~271 through `_get_strategy_signal` ~1586) — ~60 methods managing strategy loading, selection, enabling, data scoping, and signal retrieval
3. **CSS / JS injection** (`_inject_custom_styles` ~1615) — ~1100 lines of inline JS/CSS embedded as Python f-strings
4. **Side panel** (`setup_side_panel` ~2957, `_build_side_panel` ~2978, `on_side_panel_event` ~4209) — includes feedback panel code that is dormant but not yet removed
5. **Topbar / quotes / balance** (~2722-2956)
6. **Bottom bar** (`setup_bottom_bar` ~4544)
7. **Chart update pipeline** (`refresh_data` ~4936, `_refresh_data_once` ~4957, `update_chart` ~4999) — central rendering path
8. **Trade markers and tooltips** (`update_last_action_ui` ~5314 through `_ensure_action_tooltip` ~5488)
9. **Data Window** (`_build_data_window_payload` ~5727, `_update_data_window` ~5851)
10. **Equity / TCI sub-charts** (`update_equity_chart` ~5866, `update_tci_chart` ~5979)
11. **Bot loop and threading** (`bot_loop` ~6206, `start_bot` ~6162, `stop_bot` ~6191)
12. **Chart event handlers** (`on_timeframe_change` ~6067, `on_period_change` ~6098, `on_symbol_change` ~6113)

**Threading model**:
- Main thread: chart event handlers, `run()`, initial setup
- Bot-loop thread: `bot_loop()` and everything it calls — may call `chart.run_script()` directly (wrap in `try/except`); this is the established pattern
- Quote thread: `_quote_loop()` — same: direct `chart.run_script()` with `try/except`
- Note: `self._callback_queue` does NOT exist in `TradingBotGUI`; older specs referencing it are stale

**JS embedding**: `chart.run_script(f"...")` with f-string escaping (`{{` / `}}` for literal JS braces). The safe pattern for structured data is `json.dumps({...})` + `const payload = {payload}` inside the f-string.

**Specs output directory**: `agents/specs/` — Grace writes change specs here; Felix reads them before implementing.

### Strategy system

- Strategies live in `strategies/strategy_<name>.py`
- Must implement: `get_last_signal(df, verbose) -> str`
- Optional hooks: `get_last_signal_payload`, `prepare_dataframe`, `compute_signals`, `DATA_WINDOW_FIELDS`, `TIMEFRAME`, `MAGIC_NUMBER`
- **Critical isolation rule**: strategies must NOT import from `config`, `trading`, or `gui_charts`
- Order metadata encoded in comment string: `"TAo|s=strategy|r=reason"` (see `trading.build_trade_comment`)

### Manual strategy plug-in (for technical users)

A technical user can bypass the Builder by dropping a hand-crafted `.py` file into `strategies/`. The file must:
1. Be named `strategy_<name>.py`
2. Implement `get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str`
3. Never import from `config`, `trading`, or `gui_charts`
4. Use only standard library + pandas/numpy (no external dependencies not in requirements.txt)

### Strategy loading

- `main.py` uses fully dynamic strategy loading via `_load_strategy_module()` and discovery from disk
- `gui_charts.py` uses fully dynamic loading — the hardcoded `strategy_ema_rsi_trend` import was removed in TASK-009; fallback methods now return `df` or `{"signal": "none"}` when `module is None`

---

## Recent Decisions & Constraints

- **Supersistema v1 es definitivo** (2026-04-11): `src/` no es experimental. Es el runtime futuro de `main.py` y `gui_charts.py`.
- **Broker abstraction es prioridad inmediata** (2026-04-11): `IBrokerAdapter` + `IDataFeed` + `IHistoricalDataSource` seran las interfaces que desacoplan el sistema de MT5.
- **GUI is the product**: All user-facing features go in `gui_charts.py`. `main.py` is a secondary headless runner.
- **Strategies are isolated modules**: they never import from `config`, `trading`, or `gui_charts`.
- **Symbol prefix is broker-dependent**: `#Germany40` on FxPro, `DE40` on others — never hardcode new broker-specific prefixes.
- **backtesting/runtime.py** is the active backtest path in this codebase.
- **Downsampling de equity_curve** (2026-04-11): no hay downsampling. 1 punto por vela procesada.
- **Modelo fill/SL/TP** (2026-04-11): senal en vela N -> ejecucion en vela N+1; fill al open si hay gap; SL tiene prioridad sobre TP cuando ambos se tocan en la misma vela.
- **Indicadores en motor de backtest** (2026-04-11): `backtesting/runtime.py` eliminara `add_baseline_bands`, `add_supertrend`, `add_tci` del DataFrame de datos. El motor solo entrega OHLCV + `add_source_columns`; preparacion de indicadores es responsabilidad de la estrategia via `prepare_dataframe(df)`.
- **Branch status**: `supersistema-v1` fue mergeado a `main` (commit `3b68212`).

---

## Estado del Backtest GUI (post-sprint)

- `backtesting/runtime.py` — `BacktestEngine` construye `self.equity_curve` y la incluye en el resultado. El campo `"trades"` (lista completa) esta en el resultado. El campo `"closed_trades"` es solo el conteo numerico.
- La GUI actualmente muestra 8 cards de resumen. El JSON payload llega completo a JS via `window.renderBacktestPanel(payload)`.
- Los sub-charts del bot en vivo (`equity_chart`, `tci_chart`) son lightweight_charts sub-charts. La curva de equity del backtest usa SVG o Canvas inline en el panel HTML del Backtest tab.
- `backtesting/runtime.py` recibe `data_source: IHistoricalDataSource` — ya no llama a MT5 directamente.

## Estado de sprints anteriores

- **Cleanup sprint** (TASK-001 a TASK-013): completo.
- **Strategy Builder sprint** (TASK-014 a TASK-018): completo.
- **Primera Estrategia externa sprint** (TASK-019 a TASK-026): completo. ADX+DI, piramidado y sizing dinamico implementados.
- **Supersistema v1 sprint** (rama `supersistema-v1`, mergeado en commit `3b68212`): completo.
- **Backtest GUI sprint** (TASK-027 a TASK-033): completo. Equity curve, comparacion de backtests y mejoras visuales implementados.
- **Broker Abstraction sprint** (TASK-034 a TASK-041): completo. `IBrokerAdapter`, `IDataFeed`, `IHistoricalDataSource`, `MT5BrokerAdapter`, `MT5DataFeed`, `MT5HistoricalDataSource`, `DukascopyHistoricalDataSource` implementados. `backtesting/runtime.py` desacoplado de MT5 directo.
- **Strategy Quick Params sprint** (TASK-042 a TASK-044): completo. Schema PARAMS, merge logic, params injection en main.py, Quick Params panel GUI implementados.

## Known Issues / Blockers

- `ExecutionEngine` llama a `self._trading._send_order()` y `self._trading._close_position()` que son funciones privadas de `trading.py` — acoplamiento directo. No es bloqueante para los sprints activos; a resolver cuando se migre la GUI al supersistema v1.
