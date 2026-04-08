# Sprint Dashboard

_Maintained by Jarvis. Update this file whenever a task status changes, a new task enters the sprint, or a blocking task completes. The "Ready Now" table is the answer to "what can I spin up?"_

_Last updated: 2026-03-31_

---

## Dependency DAG — Current Sprint

```
TASK-011 (Grace)
   │  Touches: gui_charts.py [read-only-source]
   │  Writes:  agents/specs/TASK-011-feedback-panel-deletion.md
   │
   └──► TASK-012 (Felix)
           Touches: gui_charts.py [write]

TASK-013 (Felix)   [independent]
   Touches: CLAUDE.md [write]
```

Legend:
  ──►  "blocks / must complete before"
  [independent]  no dependency edges to/from other sprint tasks

---

## Parallelism Status

| Task | Assigned | Status | Touches | Blocker | Parallel-safe with |
|------|----------|--------|---------|---------|-------------------|
| TASK-011 | Grace | **READY** | `gui_charts.py` [read-only-source], `agents/specs/TASK-011-*.md` [write] | — | TASK-013 ✓ |
| TASK-012 | Felix | **BLOCKED** | `gui_charts.py` [write] | TASK-011 not done | — |
| TASK-013 | Felix | **READY** | `CLAUDE.md` [write] | — | TASK-011 ✓ |

### Ready Now

| Task | Agent | Why it's ready |
|------|-------|---------------|
| TASK-011 | Grace | No blockers. Soft conflict with TASK-012 (same source file) is moot — TASK-012 is itself blocked and Felix cannot start it while TASK-011 is in-progress. |
| TASK-013 | Felix | No blockers. Touches only `CLAUDE.md` — no overlap with any other ready task. |

> **Answer to "what can I spin up right now?"**
> Spin up TASK-011 (Grace) and TASK-013 (Felix) simultaneously. They touch different files and have no dependency relationship.

### Blocked

| Task | Agent | Waiting for |
|------|-------|------------|
| TASK-012 | Felix | TASK-011 — Grace's spec must exist at `agents/specs/TASK-011-feedback-panel-deletion.md` before Felix starts. |

### In Progress

_None._

---

## Conflict Matrix

|  | TASK-011 (Grace) | TASK-012 (Felix) | TASK-013 (Felix) |
|--|-----------------|-----------------|-----------------|
| **TASK-011 (Grace)** | — | Soft conflict (same source file) — moot: TASK-012 blocked | ✅ Safe |
| **TASK-012 (Felix)** | Soft conflict — moot | — | Same agent (Felix) — sequential only |
| **TASK-013 (Felix)** | ✅ Safe | Same agent (Felix) — sequential only | — |

---

## Conflict Detection Rules

Applied in order. First rule that fires is the verdict.

**Rule 1 — Dependency Gate (hard)**
If a task has `Blocked by: TASK-X` and TASK-X status ≠ `done` → BLOCKED. Stop.

**Rule 2 — Two Writers on Same File (hard)**
If two tasks both have `[write]` on the same file → cannot run simultaneously. Sequence by explicit dependency, then by priority, then Jarvis's judgment.

**Rule 3 — Writer + Read-Only-Source on Same File (soft)**
If one task `[write]` and another `[read-only-source]` share a `.py` file:
- Writer is BLOCKED → reader is safe to run (writer cannot start while reader is active).
- Writer is READY or IN-PROGRESS → soft conflict. Preferred: let spec-writer finish first. If parallelism is required, note in sprint.md that the spec's line numbers may be stale.

**Rule 4 — Spec Dir Race (soft)**
If Task A produces a spec file that Task B consumes, and both run simultaneously, Task B may read an incomplete spec. Prevention: encode spec-consumer in `Blocked by:` so Rule 1 catches it.

**Rule 5 — Same Agent, Multiple Tasks (capacity)**
Two tasks assigned to the same agent cannot run simultaneously regardless of file overlap. One agent = one session at a time.

**Rule 6 — Spec-Writer + Coder on Different Files (always safe)**
Grace/Daniel writing specs + Felix writing a different source file = no conflict. Both can run.

---

## Backlog — Upcoming Work

Items known but not yet decomposed into TASK-NNN entries. Jarvis adds them to the sprint when current sprint completes or capacity opens.

### BACKLOG-A: Backtest GUI Integration

**Description**: Wire `backtest.py` into the GUI as a new side panel tab.

**Agents required**:
- Grace (GUI spec — mandatory: new panel, threading boundary, JS interactions)
- Daniel (algorithm review — mandatory: any new metrics in backtest results)
- Felix (implementation — after both Grace spec and Daniel review are complete)

**Parallelism**: Grace (TASK-A1) and Daniel (TASK-A2) can run simultaneously.
- Grace touches `gui_charts.py` [read-only-source] + `agents/specs/` [write]
- Daniel touches `backtest.py` [read] + `agents/reviews/` [write]
- No file overlap → Rule 6 applies → safe to co-run
- Felix (TASK-A3) blocked by both A1 and A2.

**Prerequisite**: Current sprint (TASK-011, TASK-012, TASK-013) must be complete. Felix cannot work on `gui_charts.py` while TASK-012 is removing dead code from the same file.

---

### BACKLOG-B: New Strategy Modules

**Description**: Add new trading strategies to `strategies/`.

**Agents required**:
- Daniel (algorithm pre-implementation — mandatory before any strategy code is written)
- Strategy coder (implements Daniel's pseudocode spec; does not touch `gui_charts.py`)

**Parallelism**: Daniel + strategy coder on different strategies = safe (different files). Daniel writes to `agents/reviews/`; strategy coder writes to `strategies/`.

---

### BACKLOG-C: Performance Audit

**Description**: Post-implementation review of hot paths after backtest GUI integration lands.

**Agents required**: Daniel (post-implementation review — reads source files, writes `agents/reviews/`)

**Prerequisite**: BACKLOG-A must be complete.

---

## Jarvis's Update Protocol

### When a task moves to in-progress
1. Update `tasks.md`: set `Status` to `in-progress`.
2. Move the task row in the Parallelism Status table from Ready Now → In Progress.
3. Re-evaluate Rule 3 soft conflicts: if a `[read-only-source]` task was safe because the `[write]` task was blocked, and the `[write]` task is now in-progress, flag the soft conflict.

### When a task completes (status → done)
1. Update `tasks.md`: set `Status` to `done`, move entry to ## Completed section.
2. Remove the task row from the Parallelism Status table.
3. Find all tasks whose `Blocked by:` points to the completed task. Re-evaluate Rules 1–6 for each. Move newly unblocked tasks from Blocked → Ready Now if no other blocker remains.
4. Update the DAG: remove the completed node and its edges.
5. Update the conflict matrix: remove the row and column for the completed task.
6. Update the "Answer to what can I spin up?" summary line.

### When a new task enters the sprint
1. Add full entry to `tasks.md` with all 7 fields (ID, Priority, Status, Assigned, Blocked by, Blocks, Touches).
2. Add a row to the Parallelism Status table.
3. Update the DAG: add the new node and any edges.
4. Evaluate Rules 1–6 for the new task against all existing in-progress and ready tasks.
5. Update the conflict matrix: add row and column.
6. Update the "Answer to what can I spin up?" summary line.

### Spec completion checkpoint
When a spec-writer task (Grace, Daniel) completes, verify the output file exists at the path declared in `Touches:` before marking `done`. If the agent wrote to a different path, update both `tasks.md` and any `Blocked by:` references in downstream tasks.

---

## Jarvis's "What Can I Spin Up?" Algorithm

```
1. Filter tasks to Status = todo or in-progress.
2. For each todo task:
   a. Rule 1: any Blocked by task not done? → BLOCKED, skip.
   b. Rule 5: is the assigned agent already running another task? → cannot add.
   c. Rule 2: does any in-progress task [write] the same file this task [write]? → conflict.
   d. Rule 3: does any in-progress task [write] the same file this task [read-only-source]? → soft conflict, flag.
3. Remaining todo tasks with no hard blocks = Ready Now candidates.
4. Among Ready Now candidates, group by agent. Each agent contributes at most 1 task.
5. Across agents, check Rule 2 and Rule 3 between all pairs of Ready Now candidates.
6. Result: the set of tasks where no hard conflict exists between any pair.
```
