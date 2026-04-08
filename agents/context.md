# Project Context

_Last updated by Jarvis: 2026-04-05 (nuevo sprint: estrategia con ADX/DI, piramidado y sizing dinámico)_

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

**If you suspect you are missing information to complete your task** — for example, a referenced spec file doesn't exist yet, a source file contains something unexpected, or a decision required by your task has not been made — you must:
1. Stop immediately. Do not proceed with assumptions.
2. Tell the user directly in your terminal output what is missing and why it blocks you.
3. Ask the user explicitly for permission or the missing information before continuing.

This applies to all agents (Daniel, Grace, Felix, and any future agents). When in doubt, escalate — never assume.

---

## Agent Team

| Agent | Role | Definition |
|-------|------|-----------|
| **Jarvis** | Project manager — maintains this file and `tasks.md`; briefs agents before sprints | _(configured as Claude Code agent type `jarvis`)_ |
| **Daniel** | Algorithm specialist — pre-implementation algorithm selection (primary) and post-implementation review; enumerates candidates, selects and justifies the winner, produces pseudocode spec the coding agent implements verbatim; flags unclear problem statements to Jarvis before any algorithm work begins. **Jarvis must route through Daniel** for: (1) any backtesting feature work, (2) any new algorithm or indicator implementation | `agents/daniel.md` |
| **Grace** | GUI architect — pre-implementation planning specialist for `gui_charts.py`; maps safe insertion points, defines the threading zone for each change, documents JS/Python interaction patterns, and writes the change spec that Felix implements. **Jarvis must route through Grace** for: (1) any new UI panel, tab, or major section, (2) any `chart.run_script()` JS injection change, (3) any method addition/removal on `TradingBotGUI`, (4) any change touching the bot loop or threading, (5) backtest GUI integration | `agents/grace.md` |
| **Felix** | GUI coder — implements changes to `gui_charts.py` following Grace's spec (spec-driven mode) or direct task descriptions (direct mode for single-site cosmetic edits). Enforces established coding patterns: IIFE wrappers, JSON payload crossing, callback-queue threading, `getattr(config, ...)` access. Does not make architectural decisions | `agents/felix.md` |

---

## Project

**trading-agent** is a MetaTrader 5 trading bot with pluggable strategies and a TradingView-style GUI. Language: Python. The **only** entry point for users is `gui_charts.py` — all interaction happens through the graphical interface.

### What this project is

- Live trading engine supporting multiple strategies running concurrently on one or more symbols via MT5
- TradingView-style GUI (lightweight_charts + pywebview) for all user interaction: enable/disable strategies, monitor positions, view candles and indicator overlays, and performance metrics
- Backtesting engine (`backtest.py`) — fully written, will be integrated into the GUI in a future sprint

### What this project is NOT

- Not a console/headless tool (main.py is legacy; the GUI is the product)
- Not an HTTP server or webhook system (feedback_server.py is out of scope and will be deleted)
- Not a cTrader integration — MT5 only for now

---

## Current Goals

El **cleanup sprint** (TASK-001 a TASK-013) está completo. El **Strategy Builder sprint** (TASK-014 a TASK-018) está completo: el Builder visual existe, genera `.py` desde formularios y los registra sin reiniciar. `strategies/builder.py` es el módulo generador.

El equipo inicia ahora el **sprint de la Primera Estrategia externa** (TASK-019 a TASK-026): incorporar una estrategia real enviada por un colaborador. Esta estrategia requiere tres capas nuevas que el bot actual no soporta:

1. **ADX + DI** — nuevos indicadores no presentes en el catálogo (TASK-014a); la condición de entrada es un *cruce* de +DI sobre -DI, un tipo de condición no soportado por el ConditionNode actual.
2. **Piramidado** — el motor de ejecución actual abre una sola posición por señal con lot fijo; la estrategia requiere entradas adicionales piramiadas si el precio avanza 0.5×ATR desde la última entrada.
3. **Sizing dinámico y control de riesgo** — tamaño calculado como `(volumen_actual / SMA_volumen_20) × 0.5%` con techo 1% de cartera, y límite de riesgo agregado por ticker del 3%.

Antes de cualquier implementación, Daniel debe revisar y producir specs para las tres capas. Grace debe revisar cualquier cambio que requiera reflejo en la GUI.

---

## Active Configuration (config.py)

- Symbol: `#Germany40` (DAX Spot CFD on FxPro — prefix varies by broker, do not hardcode new prefixes)
- Lot: `0.01`
- SL / TP: `300` / `500` points
- Active strategies: `ema_rsi_trend`, `bollinger_rsi_reversion`, `donchian_breakout` (these are test artifacts, scheduled for deletion in TASK-018)
- Loop interval: `10s`
- Max strategy workers: `8`
- Analysis timeout: `15s`

---

## Architecture

```
MT5 Connection (mt5_connection.py)
    ↓
gui_charts.py  ←→  main.py (trading loop, strategy runner)
                       ├─ data_feed.py       → OHLCV + derived columns
                       ├─ strategies/        → pluggable modules (ThreadPoolExecutor)
                       └─ trading.py         → order placement via apply_signal()
```

### Key file sizes / risk notes

- `gui_charts.py` is **~6374 lines** (the "3000+ lines" figure in CLAUDE.md is outdated) — all edits must be **targeted and surgical**; route non-trivial changes through Grace before assigning to Felix
- `backtest.py` is well-written and stable — **do not touch** (future GUI integration)
- `trading.py`: `apply_signal()` is the sole public API for order execution; `_close_position()` and `_send_order()` are private helpers called only from within `apply_signal()` — no external callers exist

### GUI architecture (`gui_charts.py`)

The file contains a single class `TradingBotGUI` with ~90 methods. No sub-classes, no mixins. The major logical sections are:

1. **Init and chart setup** (`__init__` lines ~84–270, `setup_topbar` ~1591)
2. **Strategy registry** (`_init_strategy_registry` ~271 through `_get_strategy_signal` ~1586) — ~60 methods managing strategy loading, selection, enabling, data scoping, and signal retrieval
3. **CSS / JS injection** (`_inject_custom_styles` ~1615) — ~1100 lines of inline JS/CSS embedded as Python f-strings
4. **Side panel** (`setup_side_panel` ~2957, `_build_side_panel` ~2978, `on_side_panel_event` ~4209) — includes feedback panel code that is dormant but not yet removed
5. **Topbar / quotes / balance** (~2722–2956)
6. **Bottom bar** (`setup_bottom_bar` ~4544)
7. **Chart update pipeline** (`refresh_data` ~4936, `_refresh_data_once` ~4957, `update_chart` ~4999) — central rendering path
8. **Trade markers and tooltips** (`update_last_action_ui` ~5314 through `_ensure_action_tooltip` ~5488)
9. **Data Window** (`_build_data_window_payload` ~5727, `_update_data_window` ~5851)
10. **Equity / TCI sub-charts** (`update_equity_chart` ~5866, `update_tci_chart` ~5979)
11. **Bot loop and threading** (`bot_loop` ~6206, `start_bot` ~6162, `stop_bot` ~6191)
12. **Chart event handlers** (`on_timeframe_change` ~6067, `on_period_change` ~6098, `on_symbol_change` ~6113)

**Threading model**:
- Main thread: chart event handlers, `run()`, initial setup
- Bot-loop thread: `bot_loop()` and everything it calls — must NOT call `chart.run_script()` directly
- Quote thread: `_quote_loop()` — same restriction
- Callback thread: `_callback_loop()` — drains `self._callback_queue`; callables placed here may call `chart.run_script()`

**JS embedding**: `chart.run_script(f"...")` with f-string escaping (`{{` / `}}` for literal JS braces). The safe pattern for structured data is `json.dumps({...})` + `const payload = {payload}` inside the f-string.

**Specs output directory**: `agents/specs/` — Grace writes change specs here; Felix reads them before implementing.

### Strategy system

- Strategies live in `strategies/strategy_<name>.py`
- Must implement: `get_last_signal(df, verbose) -> str`
- Optional hooks: `get_last_signal_payload`, `prepare_dataframe`, `compute_signals`, `DATA_WINDOW_FIELDS`, `TIMEFRAME`, `MAGIC_NUMBER`
- **Critical isolation rule**: strategies must NOT import from `config`, `trading`, or `gui_charts`
- Order metadata encoded in comment string: `"TAo|s=strategy|r=reason"` (see `trading.build_trade_comment`)

### Manual strategy plug-in (for technical users)

The Builder generates strategies for non-technical users. A technical user can bypass the Builder by dropping a hand-crafted `.py` file into `strategies/`. The file must:
1. Be named `strategy_<name>.py`
2. Implement `get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str`
3. Never import from `config`, `trading`, or `gui_charts`
4. Use only standard library + pandas/numpy (no external dependencies not in requirements.txt)

TASK-018 will produce a short doc (`strategies/README.md`) capturing these rules.

### Strategy loading

- `main.py` uses fully dynamic strategy loading via `_load_strategy_module()` and discovery from disk
- `gui_charts.py` uses fully dynamic loading — the hardcoded `strategy_ema_rsi_trend` import was removed in TASK-009; fallback methods now return `df` or `{"signal": "none"}` when `module is None`

---

## Recent Decisions & Constraints

- **GUI is the product**: All user-facing features go in `gui_charts.py`. `main.py` is a secondary headless runner and should not accumulate new features.
- **Strategies are isolated modules**: they never import from `config`, `trading`, or `gui_charts`.
- **Symbol prefix is broker-dependent**: `#Germany40` on FxPro, `DE40` on others — never hardcode new broker-specific prefixes.
- **backtest.py is frozen** for this sprint: well-written, future GUI integration planned.
- **Branch status**: current branch is `futuroMain` — commit message notes it needs to be merged into `main` after cleanup.
- `_should_throttle()` and `_get_timeframe_seconds()` were removed in TASK-006 — no longer relevant.
- `close_position()` and `send_order()` were renamed to `_close_position()` / `_send_order()` in TASK-005 — no external callers.
- **Decision #4 closed 2026-04-03**: Builder exposes a timeframe selector per strategy (Option A). TASK-014 is now fully unblocked.

---

## Estado del Strategy Builder (post-TASK-018)

- `strategies/builder.py` existe con `generate_strategy_file(config_dict) -> Path`.
- La GUI tiene el panel visual de creación de estrategias en el tab "Estrategias".
- Los tres archivos de estrategia de ejemplo han sido eliminados; `ACTIVE_STRATEGIES = []` en `config.py`.
- `strategies/README.md` documenta el contrato de plug-in manual.

## Sprint de la Primera Estrategia — restricciones clave

- **ADX y +DI/-DI** no están en el catálogo de indicadores (`agents/specs/TASK-014a-indicator-catalogue.md`). Deben añadirse al catálogo y al generador.
- **Cruce de líneas** (+DI cruza por encima de -DI entre la vela N-2 y N-1) no está soportado por el `ConditionNode` actual (que solo compara valores puntuales de `df.iloc[-2]`). Daniel debe decidir la extensión del modelo.
- **Piramidado**: `apply_signal()` en `trading.py` abre una única posición por señal con lot fijo y SL/TP en puntos. La estrategia requiere múltiples entradas independientes con SL/TP calculados desde el ATR en el momento de cada entrada.
- **Sizing dinámico**: el bot usa `config.LOT` fijo. El nuevo sizing requiere acceder al balance/equity de la cuenta MT5 en tiempo real y a la SMA del volumen del instrumento.
- **Riesgo agregado 3%**: requiere consultar todas las posiciones abiertas de la estrategia y calcular el riesgo en curso antes de abrir cada nueva entrada.
- **Solo largos**: esta estrategia es long-only. No hay señales de venta corta.
- **Cada posición es independiente**: SL/TP se calculan individualmente por cada entrada (inicial o piramiada), no se comparten.

## Known Issues / Blockers

- La rama `futuroMain` todavía necesita merge a `main`.
- Los cambios de piramidado y sizing dinámico en `trading.py` tienen alto potencial de side-effects sobre estrategias ya existentes — Daniel debe diseñar la extensión de forma que `apply_signal()` existente no cambie de comportamiento para estrategias que no usen las nuevas capacidades.

---

