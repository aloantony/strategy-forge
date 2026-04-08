# Daniel — Output Templates

## Pre-Implementation Report (`agents/specs/<TASK-ID>-<slug>.md`)

```markdown
# Pre-Implementation: <function_name>

**By**: Daniel
**Date**: <YYYY-MM-DD>
**Task**: <TASK-ID>
**Status**: ready | flagged-unclear

---

## Formal Problem Statement

**Input**: <exact type, shape, constraints>
**Output**: <exact type, semantic meaning>
**Constraints**: <size bounds, latency budget, precision requirements>
**Invariants**: <what is always true about the input>

**Clarity**: ✅ clear | ⚠️ unclear — see Blocked section

---

## Candidate Algorithms

### 1. <Algorithm Name>
- **Description**: <how it works for this problem>
- **Time**: O(?) worst, O(?) average
- **Space**: O(?)
- **Verdict**: eliminated | viable | selected
- **Reason**: <why eliminated or why viable>

### 2. <Algorithm Name>
...

---

## Selected Algorithm

**Winner**: <name>

**Justification**:
Given n=<value>, called <frequency>, latency budget <budget>ms:
- <specific reason this wins over each alternative>
- <trade-offs accepted and why they are acceptable>

---

## Pseudocode Spec

function <name>(inputs):
    # <invariant assumptions that may be relied upon>
    ...
    return result

The coding agent implements this pseudocode in Python. No algorithmic decisions are left to the coding agent — only translation.

---

## Blocked (only if flagged-unclear)

<Two or more interpretations of the problem, why they lead to different algorithms, what Jarvis must clarify.>
```

---

## Post-Implementation Review (`agents/reviews/<function_name>.md`)

```markdown
# Review: <function_name> (<file_path>:<start_line>)

**Reviewed by**: Daniel
**Date**: <YYYY-MM-DD>
**Status**: complete | flagged-unclear

---

## Problem Statement

<What problem is this function solving, inferred from code + callers + context.>

**Clarity**: ✅ clear | ⚠️ unclear — see Blocked section

---

## Current Algorithm

**Name**: <algorithm name>
**Description**: <how it works — the computational approach, not just what it does>
**Time**: O(?) | **Space**: O(?)

---

## Algorithm Candidates

### 1. <Current algorithm>
- **Verdict**: currently used
- **Assessment**: correct choice | wrong choice — <reason>

### 2. <Alternative>
- **Verdict**: superior | inferior | equivalent
- **Reason**: <why, given actual n and call frequency>

---

## Finding

- [ ] Correct algorithm, optimal implementation — no change needed
- [ ] Correct algorithm, suboptimal implementation — constant-factor improvements available
- [ ] Wrong algorithm — replacement required (see Optimal Approach)

---

## Constant-Factor Analysis (if suboptimal)

- **Line <n>**: <what happens, why costly>

### Impact estimate
Called <frequency> × costs <ms> per call = <total per interval>

---

## Optimal Approach (if wrong or suboptimal)

### Pseudocode

function optimized_<name>(inputs):
    ...
    return result

### Trade-offs

| Trade-off | Detail |
|-----------|--------|
| Readability | better/worse/same |
| Correctness risk | <edge cases> |
| New dependencies | <if any> |

---

## Blocked (only if flagged-unclear)

<Two or more interpretations, what Jarvis must clarify.>
```
