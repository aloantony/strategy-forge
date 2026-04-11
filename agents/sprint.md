# Sprint Dashboard

_Maintained by Jarvis. Update this file whenever a task status changes, a new task enters the sprint, or a blocking task completes. The "Ready Now" table is the answer to "what can I spin up?"_

_Last updated: 2026-04-11_

---

## Sprint activo: Backtest GUI (TASK-027 a TASK-033)

### Dependency DAG

```
TASK-027 (Daniel)
   |  Touches: backtesting/runtime.py [read], agents/specs/ [write]
   |
   `---> TASK-028 (Grace)
           |  Touches: gui_charts.py [read-only-source], agents/specs/ [write]
           |
           `---> TASK-031 (Felix)
                   |  Touches: gui_charts.py [write], backtesting/runtime.py [write]
                   |
                   `---> TASK-033 (Felix)
                           Touches: gui_charts.py [write]

TASK-029 (Daniel)   [independent from TASK-027]
   |  Touches: backtesting/runtime.py [read], agents/specs/ [write]
   |
   `---> TASK-030 (Grace)   [also blocked by TASK-028]
           |  Touches: gui_charts.py [read-only-source], agents/specs/ [write]
           |
           `---> TASK-032 (Felix)
                   Touches: gui_charts.py [write], backtesting/runtime.py [write]
```

Legend:
  --->  "blocks / must complete before"
  [independent]  no dependency edges to/from other sprint tasks

---

### Parallelism Status

| Task | Assigned | Status | Touches | Blocker | Parallel-safe with |
|------|----------|--------|---------|---------|-------------------|
| TASK-027 | Daniel | **READY** | `backtesting/runtime.py` [read], `agents/specs/` [write] | -- | TASK-029 (same agent -- sequential) |
| TASK-028 | Grace | **BLOCKED** | `gui_charts.py` [read-only-source], `agents/specs/` [write] | TASK-027 not done | -- |
| TASK-029 | Daniel | **READY** | `backtesting/runtime.py` [read], `agents/specs/` [write] | -- | TASK-027 (same agent -- sequential) |
| TASK-030 | Grace | **BLOCKED** | `gui_charts.py` [read-only-source], `agents/specs/` [write] | TASK-029 not done, TASK-028 not done | -- |
| TASK-031 | Felix | **BLOCKED** | `gui_charts.py` [write], `backtesting/runtime.py` [write] | TASK-028 not done | -- |
| TASK-032 | Felix | **BLOCKED** | `gui_charts.py` [write], `backtesting/runtime.py` [write] | TASK-030, TASK-029 not done | -- |
| TASK-033 | Felix | **BLOCKED** | `gui_charts.py` [write] | TASK-031 not done | -- |

### Ready Now

| Task | Agent | Why it's ready |
|------|-------|---------------|
| TASK-027 | Daniel | No blockers. TASK-029 is also Daniel's but same-agent rule means sequential. Start TASK-027 first, then TASK-029. |

> **Answer to "what can I spin up right now?"**
> Spin up TASK-027 (Daniel). When TASK-027 completes: spin up TASK-028 (Grace) and TASK-029 (Daniel) -- they touch different files. When TASK-028 is done: unblock TASK-031 (Felix). When TASK-029 is done and TASK-028 is done: unblock TASK-030 (Grace). When TASK-031 is done: unblock TASK-033 (Felix). When TASK-030 and TASK-029 both done: unblock TASK-032 (Felix).

### Blocked

| Task | Agent | Waiting for |
|------|-------|------------|
| TASK-028 | Grace | TASK-027 -- spec must know the exact fields in the backend result |
| TASK-029 | Daniel | Nothing (ready after TASK-027 or in parallel if Daniel has capacity) |
| TASK-030 | Grace | TASK-029 (backend shape) AND TASK-028 (must not overlap insertion points) |
| TASK-031 | Felix | TASK-028 -- Grace's spec must exist before Felix implements |
| TASK-032 | Felix | TASK-030 (Grace spec) AND TASK-029 (Daniel backend spec) |
| TASK-033 | Felix | TASK-031 -- export button goes in the results section established by TASK-031 |

### In Progress

_None._

---

## Siguiente sprint: Broker Abstraction (TASK-034 a TASK-039)

**Decision de secuencia**: La mayoria de las tareas de Broker Abstraction esperan a que termine el sprint de Backtest GUI, porque TASK-031/032 escriben `backtesting/runtime.py` y TASK-037 tambien escribe ese archivo. Solaparlos causaria conflictos.

**Excepcion**: TASK-034 (Daniel, solo spec -- lee `trading.py` y `src/runtime/execution_engine.py`, no escribe ningun archivo de runtime) puede arrancar en paralelo con el sprint activo cuando Daniel tenga capacidad despues de TASK-027 y TASK-029.

### Dependency DAG (Broker Abstraction)

```
TASK-034 (Daniel) [puede correr en paralelo con el sprint activo]
   |  Touches: trading.py [read-only], src/runtime/execution_engine.py [read-only], agents/specs/ [write]
   |
   +---> TASK-035 (Felix)
   |       |  Touches: src/broker/ [create], src/runtime/execution_engine.py [write], main.py [write]
   |       |
   |       `---> TASK-038 (Grace)
   |               |  Touches: gui_charts.py [read-only-source], agents/specs/ [write]
   |               |
   |               `---> TASK-039 (Felix)  [also blocked by TASK-037]
   |                       Touches: gui_charts.py [write]
   |
   `---> TASK-036 (Daniel)  [also blocked by TASK-034]
           |  Touches: data_feed.py [read-only], backtesting/runtime.py [read-only], agents/specs/ [write]
           |
           `---> TASK-037 (Felix)  [also blocked by TASK-033]
                   |  Touches: src/data/ [create], backtesting/runtime.py [write], main.py [write]
                   |
                   `---> TASK-039 (Felix)
```

### Parallelism Status (Broker Abstraction)

| Task | Assigned | Status | Touches | Blocker |
|------|----------|--------|---------|---------|
| TASK-034 | Daniel | **READY** (can start in parallel with active sprint) | `trading.py` [read-only], `src/runtime/execution_engine.py` [read-only], `agents/specs/` [write] | -- |
| TASK-035 | Felix | **BLOCKED** | `src/broker/` [create], `src/runtime/execution_engine.py` [write], `main.py` [write] | TASK-034 not done |
| TASK-036 | Daniel | **BLOCKED** | `data_feed.py` [read-only], `backtesting/runtime.py` [read-only], `agents/specs/` [write] | TASK-034 not done (same agent -- sequential) |
| TASK-037 | Felix | **BLOCKED** | `src/data/` [create], `backtesting/runtime.py` [write], `main.py` [write] | TASK-036 not done, TASK-033 not done |
| TASK-038 | Grace | **BLOCKED** | `gui_charts.py` [read-only-source], `agents/specs/` [write] | TASK-035 not done |
| TASK-039 | Felix | **BLOCKED** | `gui_charts.py` [write] | TASK-037 not done, TASK-038 not done |

---

## Conflict Matrix (sprint activo)

|  | TASK-027 | TASK-028 | TASK-029 | TASK-030 | TASK-031 | TASK-032 | TASK-033 |
|--|:--------:|:--------:|:--------:|:--------:|:--------:|:--------:|:--------:|
| **TASK-027** | -- | Rule 4: spec-consumer blocked | Same agent -- sequential | -- | Rule 4 cascade | -- | -- |
| **TASK-028** | -- | -- | Safe | Rule 4: spec-consumer blocked | Rule 4: spec-consumer blocked | -- | -- |
| **TASK-029** | Same agent | Safe | -- | Rule 4: spec-consumer blocked | -- | Rule 4 cascade | -- |
| **TASK-030** | -- | Same agent | -- | -- | Safe (diff files) | Rule 4: spec-consumer blocked | -- |
| **TASK-031** | -- | -- | -- | Safe | -- | Same agent -- sequential | Same agent -- sequential |
| **TASK-032** | -- | -- | -- | -- | Same agent | -- | Same agent |
| **TASK-033** | -- | -- | -- | -- | Same agent | Same agent | -- |

---

## Conflict Detection Rules

Applied in order. First rule that fires is the verdict.

**Rule 1 -- Dependency Gate (hard)**
If a task has `Blocked by: TASK-X` and TASK-X status != `done` -> BLOCKED. Stop.

**Rule 2 -- Two Writers on Same File (hard)**
If two tasks both have `[write]` on the same file -> cannot run simultaneously. Sequence by explicit dependency, then by priority, then Jarvis's judgment.

**Rule 3 -- Writer + Read-Only-Source on Same File (soft)**
If one task `[write]` and another `[read-only-source]` share a `.py` file:
- Writer is BLOCKED -> reader is safe to run (writer cannot start while reader is active).
- Writer is READY or IN-PROGRESS -> soft conflict. Preferred: let spec-writer finish first.

**Rule 4 -- Spec Dir Race (soft)**
If Task A produces a spec file that Task B consumes, and both run simultaneously, Task B may read an incomplete spec. Prevention: encode spec-consumer in `Blocked by:` so Rule 1 catches it.

**Rule 5 -- Same Agent, Multiple Tasks (capacity)**
Two tasks assigned to the same agent cannot run simultaneously regardless of file overlap. One agent = one session at a time.

**Rule 6 -- Spec-Writer + Coder on Different Files (always safe)**
Grace/Daniel writing specs + Felix writing a different source file = no conflict. Both can run.

---

## Backlog

_BACKLOG-B (New Strategy Modules) and BACKLOG-C (Performance Audit) remain pending for future sprints after Broker Abstraction completes._

---

## Jarvis's Update Protocol

### When a task moves to in-progress
1. Update `tasks.md`: set `Status` to `in-progress`.
2. Move the task row in the Parallelism Status table from Ready Now -> In Progress.
3. Re-evaluate Rule 3 soft conflicts.

### When a task completes (status -> done)
1. Update `tasks.md`: set `Status` to `done`, move entry to Completed section.
2. Remove the task row from the Parallelism Status table.
3. Find all tasks whose `Blocked by:` points to the completed task. Re-evaluate Rules 1-6 for each. Move newly unblocked tasks from Blocked -> Ready Now if no other blocker remains.
4. Update the DAG: remove the completed node and its edges.
5. Update the conflict matrix: remove the row and column for the completed task.
6. Update the "Answer to what can I spin up?" summary line.

### When a new task enters the sprint
1. Add full entry to `tasks.md` with all 7 fields (ID, Priority, Status, Assigned, Blocked by, Blocks, Touches).
2. Add a row to the Parallelism Status table.
3. Update the DAG: add the new node and any edges.
4. Evaluate Rules 1-6 for the new task against all existing in-progress and ready tasks.
5. Update the conflict matrix: add row and column.
6. Update the "Answer to what can I spin up?" summary line.

### Spec completion checkpoint
When a spec-writer task (Grace, Daniel) completes, verify the output file exists at the path declared in `Touches:` before marking `done`. If the agent wrote to a different path, update both `tasks.md` and any `Blocked by:` references in downstream tasks.

---

## Jarvis's "What Can I Spin Up?" Algorithm

```
1. Filter tasks to Status = todo or in-progress.
2. For each todo task:
   a. Rule 1: any Blocked by task not done? -> BLOCKED, skip.
   b. Rule 5: is the assigned agent already running another task? -> cannot add.
   c. Rule 2: does any in-progress task [write] the same file this task [write]? -> conflict.
   d. Rule 3: does any in-progress task [write] the same file this task [read-only-source]? -> soft conflict, flag.
3. Remaining todo tasks with no hard blocks = Ready Now candidates.
4. Among Ready Now candidates, group by agent. Each agent contributes at most 1 task.
5. Across agents, check Rule 2 and Rule 3 between all pairs of Ready Now candidates.
6. Result: the set of tasks where no hard conflict exists between any pair.
```
