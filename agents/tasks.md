# Task Backlog — Índice

_Mantenido por Jarvis. El detalle completo de cada tarea está en `agents/tasks/<TASK-ID>.md`._
_Para actualizar el estado de tu tarea, edita solo tu task file — Jarvis actualiza este índice._

<!-- hook-permission: OFF -->
<!-- jarvis-protocol: set OFF before editing this file; ask the human before restoring ON -->

---

## Active / Todo

_Sin tareas activas. Próximo sprint por definir (ver Backlog)._

---

## Completed

| ID | Assigned | Resumen |
|----|----------|---------|
| TASK-055 | Daniel | Review desacoplamiento completo: sin callers externos a `trading._send_order` / `trading._close_position` |
| TASK-054 | Alex | MT5BrokerAdapter desacoplado de trading.py; `modify_tp` implementado; `build_trade_comment` movido a `src/broker/comment.py` |
| TASK-053 | Daniel | Spec desacoplamiento ExecutionEngine Broker (`agents/specs/TASK-053-broker-decoupling-spec.md`) |
| TASK-052 | Felix | Integración Dukascopy en GUI backtest completa |
| TASK-051 | Alex | Datasource selection backend implementado |
| TASK-050 | Grace | Spec GUI datasource selection (`agents/specs/TASK-050-datasource-gui-spec.md`) |
| TASK-049 | Daniel | Spec datasource selection backend (`agents/specs/TASK-049-datasource-selection-spec.md`) |
| TASK-048 | Felix | GUI Polish — item 3 implementado |
| TASK-047 | Felix | GUI Polish — item 2 implementado |
| TASK-046 | Felix | GUI Polish — item 1 implementado |
| TASK-045 | Grace | Spec GUI Polish (`agents/specs/TASK-045-gui-polish-spec.md`) |
| TASK-044 | Felix | Quick Params panel + main.py injection implementados |
| TASK-043 | Grace | Spec GUI Quick Params (`agents/specs/TASK-043-quick-params-gui-spec.md`) |
| TASK-042 | Daniel | Schema PARAMS + pseudocode para main.py y generator.py |
| TASK-041 | Alex | DukascopyHistoricalDataSource implementado en `src/data/` |
| TASK-040 | Daniel | Validación símbolo Dukascopy para DAX |
| TASK-039 | Felix | Integración GUI broker adapter en `gui_charts.py` |
| TASK-038 | Grace | Spec GUI broker adapter integration (`agents/specs/TASK-038-gui-broker-adapter-integration.md`) |
| TASK-037 | Alex | MT5DataFeed, MT5HistoricalDataSource, desacoplamiento backtesting/runtime.py |
| TASK-036 | Daniel | Spec data provider (`agents/specs/TASK-036-data-provider-spec.md`) |
| TASK-035 | Felix | IBrokerAdapter wired in ExecutionEngine |
| TASK-034 | Daniel | IBrokerAdapter spec (`agents/specs/TASK-034-ibroker-adapter-spec.md`) |
| TASK-026 | Felix | Cambios GUI para piramidado implementados en `gui_charts.py` |
| TASK-025 | Felix | Estrategia ADX+DI con piramidado y sizing dinámico integrada |
| TASK-024 | Felix | Sizing dinámico y riesgo agregado implementados en `trading.py` |
| TASK-023 | Felix | Piramidado implementado en `trading.py` |
| TASK-022 | Grace | Spec GUI para piramidado (`agents/specs/TASK-022-pyramiding-gui-spec.md`) |
| TASK-021 | Daniel | Spec de sizing dinámico y riesgo agregado |
| TASK-020 | Daniel | Spec de piramidado |
| TASK-019 | Daniel | ADX+DI catálogo, columnas y modelo de cruce |
| TASK-018 | TBD | Eliminadas estrategias de ejemplo; `strategies/README.md` creado |
| TASK-017 | TBD | `strategies/builder.py` con `generate_strategy_file` implementado |
| TASK-016 | Felix | Strategy Builder UI en `gui_charts.py` |
| TASK-015 | Grace | Spec del Builder UI en `agents/specs/TASK-015-strategy-builder-gui-spec.md` |
| TASK-014c | Daniel | Schema + pseudocode del generador en `agents/specs/TASK-014c-...md` |
| TASK-014b | Daniel | Modelo `ConditionNode` + emitter recursivo en `agents/specs/TASK-014b-...md` |
| TASK-014a | Daniel | Catálogo de indicadores en `agents/specs/TASK-014a-...md` |
| TASK-013 | Felix | `CLAUDE.md` actualizado (líneas, referencias obsoletas eliminadas) |
| TASK-012 | Felix | Panel de feedback eliminado de `gui_charts.py` |
| TASK-011 | Grace | Spec de eliminación del panel de feedback |
| TASK-010 | Claude Code | `print()` statements eliminados; `log_message()` convertido a stub |
| TASK-009 | Claude Code | Import hardcodeado de `strategy_ema_rsi_trend` reemplazado por registro dinámico |
| TASK-008 | Claude Code | `log_strategy()` eliminado de los tres archivos de estrategia |
| TASK-007 | Claude Code | `print_strategy_status()` y `_format_number()` eliminados de `main.py` |
| TASK-006 | Claude Code | Throttling (`_should_throttle`, `_get_timeframe_seconds`) eliminado |
| TASK-005 | Claude Code | `close_position` y `send_order` renombradas a privadas |
| TASK-004 | Claude Code | `config.print_config()` eliminada |
| TASK-003 | Claude Code | Variables `FEEDBACK_*` eliminadas de `config.py` |
| TASK-002 | Claude Code | `TEST_MODE` y `get_test_signal()` eliminados |
| TASK-001 | Claude Code | Archivos fuera de scope eliminados; `.env` purgado del historial git |
