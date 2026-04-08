# Task Backlog — Índice

_Mantenido por Jarvis. El detalle completo de cada tarea está en `agents/tasks/<TASK-ID>.md`._
_Para actualizar el estado de tu tarea, edita tanto este índice como tu task file._

<!-- hook-permission: ON -->
<!-- jarvis-protocol: set OFF before editing this file; ask the human before restoring ON -->

---

## Active / Todo

### Sprint: Primera Estrategia Externa (TASK-019 a TASK-026)

| ID | Status | Assigned | Blocked by | Blocks |
|----|--------|----------|------------|--------|
| [TASK-019](tasks/TASK-019.md) | done | Daniel | — | TASK-025 |
| [TASK-020](tasks/TASK-020.md) | done | Daniel | — | TASK-022, TASK-023 |
| [TASK-021](tasks/TASK-021.md) | done | Daniel | — | TASK-022, TASK-024 |
| [TASK-022](tasks/TASK-022.md) | done | Grace | TASK-020, TASK-021 | TASK-026 |
| [TASK-023](tasks/TASK-023.md) | done | Felix | TASK-020 | TASK-025 |
| [TASK-024](tasks/TASK-024.md) | done | Felix | TASK-021 | TASK-025 |
| [TASK-025](tasks/TASK-025.md) | done | Felix | TASK-019, TASK-023, TASK-024 | — |
| [TASK-026](tasks/TASK-026.md) | done | Felix | TASK-022 | — |

---

## Completed

| ID | Assigned | Resumen |
|----|----------|---------|
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
