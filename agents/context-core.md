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

## Active Sprints

**Sprint A — Backtest GUI** (TASK-027 → 033): Enrich the Backtest tab with trade table, equity curve, drawdown chart, strategy comparison, CSV export. Daniel specs → Grace specs → Felix implements.

**Sprint B — Broker Abstraction** (TASK-034 → 040): `IBrokerAdapter` + `IDataFeed` + `IHistoricalDataSource` to decouple from MT5. TASK-034 and TASK-040 (Daniel, spec/spike only) run in parallel with Sprint A. Rest of Sprint B waits for Sprint A completion.

---

## File Hygiene Rules

- **context-core.md**: max 60 lines. Escalation + team table + sprint summary only.
- **Role files** (daniel.md, grace.md, felix.md): max 150 lines. Patterns/templates go in `agents/templates/`.
- **Spec files** — Daniel: max 400 lines. Grace: max 250 lines (must include `## Backend Summary` so Felix never needs to read Daniel's spec).
- **Task files**: self-contained. Jarvis embeds a `## Context slice` (max 10 lines) with what the agent needs.
- **agents/tasks.md**: compact index only. Never write task detail here — only the one-row table entry.
