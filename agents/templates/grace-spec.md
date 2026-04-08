# Grace — GUI Change Spec Template

## Output file: `agents/specs/<TASK-ID>-<slug>-gui-spec.md`

```markdown
# GUI Change Spec: <feature_name>

**By**: Grace
**Date**: <YYYY-MM-DD>
**Task**: <TASK-ID>
**Status**: ready | flagged-blocked

---

## Summary

<One paragraph: what this change does and why it is safe to implement now.>

---

## Affected Methods

| Method | File location (approx line) | Change type | Threading context |
|--------|---------------------------|-------------|-------------------|
| `method_name` | ~NNNN | new / modify / caller only | main / bot-loop / quote |

---

## New Instance Variables (if any)

List any new `self.*` attributes, their types, initial values, and where in `__init__` they must be initialized.

---

## Threading Analysis

For each method in a non-main-thread context:
- What currently happens when it needs to update the GUI
- What this spec requires and how it stays within the callback-queue pattern
- Explicitly confirm: "No `chart.run_script()` call from bot-loop or quote thread."

---

## JavaScript Interaction Points

### <interaction name>

- **Pattern**: Python→JS | JS→Python | Python→JS with JSON
- **Trigger**: <what causes this>
- **Data crossing the boundary**: <payload description>
- **Handler registration** (JS→Python only): `self.chart.win.handlers["<name>"] = self.<method>`
- **Brace budget** (Python→JS only): <N levels of nested {{ }} expected>
- **Constraints**: <escaping or ordering requirements>

---

## Insertion Point Map

### <method or block name>

**Location**: After line ~NNNN (`<landmark>`), before line ~NNNN (`<landmark>`)

**What changes**: <precise description>

**What must NOT change**: <adjacent code to preserve>

**Pseudocode**:
method_name(args):
    # preconditions
    ...
    return value

---

## Invariant Checklist

- [ ] No `chart.run_script()` from non-main-thread context
- [ ] DOM elements use `getElementById` guard before creation
- [ ] New config accesses use `getattr(config, "KEY", default)` pattern
- [ ] New `self.*` variables initialized in `__init__` before first use
- [ ] Strategy registry writes only from main thread
- [ ] Any new JS→Python handler name is unique (grep confirms no collision)

---

## Blocked (only if flagged-blocked)

<What is unclear, what Jarvis must decide before this spec can be completed.>
```
