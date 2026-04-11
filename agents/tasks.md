# Task Backlog — Índice

_Mantenido por Jarvis. El detalle completo de cada tarea está en `agents/tasks/<TASK-ID>.md`._
_Para actualizar el estado de tu tarea, edita tanto este índice como tu task file._

<!-- hook-permission: OFF -->
<!-- jarvis-protocol: set OFF before editing this file; ask the human before restoring ON -->

---

## Active / Todo

### Sprint: Backtest GUI — Mejoras visuales (TASK-027 a TASK-033)

| ID | Status | Assigned | Blocked by | Blocks |
|----|--------|----------|------------|--------|
| [TASK-027](tasks/TASK-027.md) | todo | Daniel | — | TASK-028 |
| [TASK-028](tasks/TASK-028.md) | todo | Grace | TASK-027 | TASK-031 |
| [TASK-029](tasks/TASK-029.md) | todo | Daniel | — | TASK-030 |
| [TASK-030](tasks/TASK-030.md) | todo | Grace | TASK-029, TASK-028 | TASK-032 |
| [TASK-031](tasks/TASK-031.md) | todo | Felix | TASK-028 | TASK-033 |
| [TASK-032](tasks/TASK-032.md) | todo | Felix | TASK-030, TASK-029 | — |
| [TASK-033](tasks/TASK-033.md) | todo | Felix | TASK-031 | — |

### Siguiente sprint: Broker Abstraction (TASK-034 a TASK-039)

_Comienza después de que el sprint de Backtest GUI esté completo, con la excepción de TASK-034 y TASK-036 que son specs (solo lectura de archivos existentes, sin escritura en runtime.py) y pueden iniciarse en paralelo al Backtest GUI sprint cuando Daniel tenga capacidad._

| ID | Status | Assigned | Blocked by | Blocks |
|----|--------|----------|------------|--------|
| [TASK-034](tasks/TASK-034.md) | todo | Daniel | — | TASK-035, TASK-036, TASK-038 |
| [TASK-035](tasks/TASK-035.md) | todo | Felix | TASK-034 | TASK-038 |
| [TASK-036](tasks/TASK-036.md) | todo | Daniel | TASK-034 | TASK-037 |
| [TASK-037](tasks/TASK-037.md) | todo | Felix | TASK-036, TASK-033 | TASK-039 |
| [TASK-038](tasks/TASK-038.md) | todo | Grace | TASK-035 | TASK-039 |
| [TASK-039](tasks/TASK-039.md) | todo | Felix | TASK-037, TASK-038 | — |

---

## Completed

| ID | Assigned | Resumen |
|----|----------|---------|
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
