# Context Core

_Read by all agents at task start. For full architecture, decisions, and history: `agents/context.md` (Jarvis only)._

---

## Escalation

If blocked, ambiguous, or missing info: **stop and escalate to Jarvis**.
- Write question to `agents/questions/<TASK-ID>-<slug>.md`
- Set task status to `blocked` in your task file and `agents/tasks.md`
- Never assume or resolve unilaterally

---

## Agent Team

| Agent | Role | File |
|-------|------|------|
| Jarvis | Project manager — maintains context.md, tasks.md, briefs agents | `.claude/agents/jarvis.md` |
| Daniel | Algorithm specialist — pre-impl spec & post-impl review. No source edits. | `agents/daniel.md` |
| Grace | GUI architect — pre-impl planning for `gui_charts.py`. No source edits. | `agents/grace.md` |
| Felix | GUI coder — implements Grace's specs in `gui_charts.py` | `agents/felix.md` |
| Alex | Backend coder — implementa specs de Daniel en archivos de backend (backtesting, src/data, main.py) | `agents/alex.md` |

---

## Active Architecture Direction

**Application Services Extraction**: the GUI remains a visual entrypoint, but business processes move into reusable services under `src/application/` and backend/runtime modules. Backtest request construction now starts in `src/application/backtest_service.py`; further process changes should follow this pattern.

Routing rule: visual-only GUI work → Grace/Felix. Process orchestration, service extraction, backtesting, runtime, broker/data, persistence → Daniel/Alex when non-trivial.

---

## File Hygiene Rules

- **context-core.md**: max 60 lines. Escalation + team table + sprint summary only.
- **Role files** (daniel.md, grace.md, felix.md): max 150 lines. Patterns/templates go in `agents/templates/`.
- **Spec files** — Daniel: max 400 lines. Grace: max 250 lines (must include `## Backend Summary` so Felix never needs to read Daniel's spec).
- **Task files**: self-contained. Jarvis embeds a `## Context slice` (max 10 lines) with what the agent needs.
- **agents/tasks.md**: compact index only. Never write task detail here — only the one-row table entry.
