# Pre-Implementation: ConditionNode model and emit_condition emitter

**By**: Daniel
**Date**: 2026-04-04
**Task**: TASK-014b
**Status**: ready

---

## Formal Problem Statement

**Problem A — ConditionNode data model**

**Input**: User-defined condition logic assembled in the GUI combinator: logical groups (AND, OR), leaf comparisons (left operand, operator, right operand), and arbitrary nesting of groups within groups.

**Output**: A JSON-serializable recursive data structure (`ConditionNode`) that unambiguously represents any valid condition tree, can be persisted to disk, and can be round-tripped between the GUI (JS) and the Python generator without loss of information.

**Constraints**:
- Must support AND, OR, and arbitrary nesting (confirmed design decision #1, `agents/context.md`)
- Left operand of a leaf: always a column name string from the indicator catalogue (TASK-014a)
- Right operand of a leaf: either a column name string OR a numeric scalar (int/float) — these two cases must be unambiguously distinguishable in the serialized form
- Operators: `<`, `>`, `<=`, `>=`, `==`, `!=` (all indicators are numeric — no string comparison operators needed)
- Must be round-trippable through `json.dumps` / `json.loads` without a custom serializer

**Invariants**:
- All column names in the tree are drawn from the catalogue produced by TASK-014a
- All group nodes (AND/OR) have at least one child
- The model carries no runtime state — it is a pure data description

**Clarity**: ✅ clear

---

**Problem B — `emit_condition` recursive emitter**

**Input**: A single `ConditionNode` root (the data model from Problem A), one for the buy condition and one for the sell condition.

**Output**: A Python expression string, valid for embedding verbatim in an `if` statement in a generated `.py` strategy file. Column references emit as `df.iloc[-2]["col_name"]`; scalar constants emit as their Python literal value.

**Constraints**:
- Called at **code-generation time** (user presses "Save") — not in the trading loop. Latency budget is irrelevant.
- Input size: a condition tree with at most 5–10 levels of nesting and at most ~20 leaf nodes (practical upper bound from any reasonable trading strategy). This is not a data-structure problem at scale.
- The emitted string is inserted into the generated `.py` file as source code. It must be syntactically valid Python.
- Parenthesization must correctly encode precedence: `A OR (B AND C)` must not emit as `A or B and C` (Python's `and` has higher precedence than `or`; relying on implicit precedence would cause errors when the user creates `(A OR B) AND C`).

**Invariants**:
- The emitter is called only after the validator has confirmed the tree is structurally valid (no empty children, valid operators, valid column names)
- The emitter never modifies the input tree — it is a pure read-only transformation

**Clarity**: ✅ clear

---

## Candidate Algorithms

### Data model — right operand type disambiguation

Three approaches for distinguishing a scalar constant from a column name reference in the `right` field of a leaf node:

#### Option 1: JSON native type inference
- **Description**: `right` is a JSON `number` for scalars, a JSON `string` for column references. Python check: `isinstance(node["right"], (int, float))` for scalar, `isinstance(node["right"], str)` for column.
- **Example**: `{"right": 30}` (scalar), `{"right": "ema_9"}` (column)
- **Space**: no extra fields
- **Verdict**: selected
- **Reason**: JSON's type system is unambiguous here — no valid column name is a JSON number, no valid scalar is a non-numeric string. Zero extra fields. Self-documenting at the JSON level. The `json` module in Python guarantees this mapping. Both the JS GUI and the Python generator can apply the same check.

#### Option 2: Explicit type tag field
- **Description**: Add a `"right_type": "scalar" | "column"` field alongside `"right_value"`.
- **Example**: `{"right_type": "scalar", "right_value": 30}`, `{"right_type": "column", "right_value": "ema_9"}`
- **Space**: one extra field per leaf node
- **Verdict**: eliminated
- **Reason**: More verbose with no disambiguation benefit over Option 1. The type tag is redundant — the JSON type already carries the information. More fields means more schema to maintain.

#### Option 3: Inline type object
- **Description**: `right` is always an object: `{"type": "scalar", "value": 30}` or `{"type": "column", "name": "ema_9"}`.
- **Space**: nested object per leaf
- **Verdict**: eliminated
- **Reason**: Deepens nesting for no gain. Makes simple conditions harder to read in the JSON representation. The context.md recommendation already uses flat `right` values, and Option 1 validates that recommendation.

---

### Data model — tree branching structure

#### Option A: N-ary tree (selected)
- **Description**: Each AND/OR group node has a `children` array with N ≥ 1 elements (validator enforces N ≥ 2).
- **Time/Space for emitter**: O(N) where N = total nodes — each node visited once.
- **Verdict**: selected
- **Reason**: `A AND B AND C` is naturally a 3-child AND node. A binary tree forces artificial nesting: `AND(AND(A, B), C)`, which produces redundant parentheses in the emitted code and is awkward to construct in the GUI (the user adds conditions to a group, not to a binary tree). N-ary is the correct structural match.

#### Option B: Binary tree
- **Description**: Each AND/OR node has exactly `left` and `right` children.
- **Verdict**: eliminated
- **Reason**: Semantically equivalent but structurally wrong. Forces the GUI to manage artificial nesting when the user adds a third condition to a group. Produces redundant parentheses in emitted code.

---

### Emitter algorithm

#### Algorithm 1: Recursive descent (structural recursion)
- **Description**: The emitter function dispatches on `node["type"]`. For leaf nodes: emit `df.iloc[-2]["col"] op value`. For AND/OR nodes: recursively emit each child, join with `" and "` / `" or "`, wrap in parentheses.
- **Time**: O(N) where N = total nodes in tree
- **Space**: O(D) where D = tree depth (call stack frames)
- **Verdict**: selected
- **Reason**: Given actual tree sizes (D ≤ 10, N ≤ 20), this is the simplest and most readable implementation. The call stack depth is bounded at D ≤ 10 — Python's recursion limit is 1000, so no risk. The emitter runs at code-generation time (user presses "Save"), not in the trading loop. Even if it were slow, performance has zero impact. Recursive descent is the canonical approach for tree transformation and matches the structure of the data model exactly.

#### Algorithm 2: Iterative post-order traversal with explicit stack
- **Description**: Use an explicit stack to perform post-order traversal. Process children before parents. Store sub-results in a dictionary keyed by node identity, then build the parent expression from the stored child results.
- **Time**: O(N)
- **Space**: O(N) — explicit stack may hold all nodes
- **Verdict**: eliminated
- **Reason**: Correct algorithm choice only when stack depth is a concern (e.g., N=10,000 deep trees, or environments with very small stack limits). Neither applies here. The added complexity (explicit stack management, result accumulation map) is not justified. Wrong algorithm for this input size.

#### Algorithm 3: Template rendering (pre-built expression lookup)
- **Description**: Build a lookup table of all possible sub-expressions by iterating the tree, then assemble the final expression from the table.
- **Verdict**: eliminated
- **Reason**: Not applicable. The condition tree is unbounded in structure — templates work for fixed schemas. There is no fixed template here.

---

## Selected Algorithms

**Data model right-operand typing**: JSON native type inference (Option 1)

**Tree branching structure**: N-ary tree (Option A)

**Emitter**: Recursive descent (Algorithm 1)

**Justification**:
- The emitter runs once per user save action — not per trading cycle. Performance irrelevant.
- Actual input: N ≤ 20 nodes, D ≤ 10 depth, well within recursive descent's safe zone.
- Recursive descent is a 1-to-1 structural mirror of the tree model — the simplest correct implementation.
- JSON native type inference eliminates an extra field per leaf node and is unambiguous given that no valid column name is a JSON number.

**Context.md recommendation**: Confirmed with one explicit addition — the `right` field's type ambiguity is resolved by JSON native typing. The recommended structure in `context.md` already uses this convention implicitly (`30` is a JSON number, `"ema_20"` is a JSON string). This spec makes that rule explicit and normative.

---

## ConditionNode — Formal Definition

### JSON Schema (normative)

```json
{
  "$defs": {
    "ConditionLeaf": {
      "type": "object",
      "required": ["type", "left", "op", "right"],
      "additionalProperties": false,
      "properties": {
        "type":  { "const": "condition" },
        "left":  {
          "type": "string",
          "description": "Column name from the indicator catalogue (e.g. 'rsi_14', 'close', 'ema_9')"
        },
        "op":    { "enum": ["<", ">", "<=", ">=", "==", "!="] },
        "right": {
          "description": "Scalar constant (JSON number) OR column name (JSON string). Type is the discriminator.",
          "oneOf": [
            { "type": "number",  "description": "Scalar constant — emitted as a Python literal" },
            { "type": "string",  "description": "Column name — emitted as df.iloc[-2][\"name\"]" }
          ]
        }
      }
    },
    "ConditionGroup": {
      "type": "object",
      "required": ["type", "children"],
      "additionalProperties": false,
      "properties": {
        "type": { "enum": ["AND", "OR"] },
        "children": {
          "type": "array",
          "items": { "$ref": "#/$defs/ConditionNode" },
          "minItems": 1,
          "description": "Validator enforces minItems: 2. Emitter tolerates minItems: 1."
        }
      }
    },
    "ConditionNode": {
      "oneOf": [
        { "$ref": "#/$defs/ConditionLeaf" },
        { "$ref": "#/$defs/ConditionGroup" }
      ]
    }
  }
}
```

### Field summary table

| Field | Present on | Type | Semantics |
|-------|-----------|------|-----------|
| `type` | All nodes | string | Discriminator: `"condition"`, `"AND"`, `"OR"` |
| `left` | Leaf only | string | Column name from indicator catalogue |
| `op` | Leaf only | string | One of `<`, `>`, `<=`, `>=`, `==`, `!=` |
| `right` | Leaf only | number \| string | JSON number → scalar constant; JSON string → column name |
| `children` | Group only | array of ConditionNode | Ordered list of child nodes (N ≥ 2 enforced by validator) |

---

## Non-Trivial JSON Example

Two levels of nesting: `(A AND B) OR (C AND D)`, where:
- A: RSI-14 is below 30 (oversold)
- B: Close is above EMA-9 (price recovering)
- C: Close breaks above Bollinger upper band (period 20)
- D: Volume ratio (lookback 30) is above 1.5 (volume confirmation)

```json
{
  "type": "OR",
  "children": [
    {
      "type": "AND",
      "children": [
        {
          "type": "condition",
          "left": "rsi_14",
          "op": "<",
          "right": 30
        },
        {
          "type": "condition",
          "left": "close",
          "op": ">",
          "right": "ema_9"
        }
      ]
    },
    {
      "type": "AND",
      "children": [
        {
          "type": "condition",
          "left": "close",
          "op": ">",
          "right": "bb_upper_20"
        },
        {
          "type": "condition",
          "left": "volume_ratio_30",
          "op": ">",
          "right": 1.5
        }
      ]
    }
  ]
}
```

Expected emitter output:
```
((df.iloc[-2]["rsi_14"] < 30 and df.iloc[-2]["close"] > df.iloc[-2]["ema_9"]) or (df.iloc[-2]["close"] > df.iloc[-2]["bb_upper_20"] and df.iloc[-2]["volume_ratio_30"] > 1.5))
```

A deeper nesting example: `((A AND B) OR C) AND D` (three levels):

```json
{
  "type": "AND",
  "children": [
    {
      "type": "OR",
      "children": [
        {
          "type": "AND",
          "children": [
            {"type": "condition", "left": "rsi_14", "op": "<", "right": 30},
            {"type": "condition", "left": "close", "op": ">", "right": "ema_9"}
          ]
        },
        {
          "type": "condition",
          "left": "supertrend_dir",
          "op": "==",
          "right": 1
        }
      ]
    },
    {
      "type": "condition",
      "left": "volume_ratio_30",
      "op": ">",
      "right": 1.2
    }
  ]
}
```

Expected emitter output:
```
(((df.iloc[-2]["rsi_14"] < 30 and df.iloc[-2]["close"] > df.iloc[-2]["ema_9"]) or df.iloc[-2]["supertrend_dir"] == 1) and df.iloc[-2]["volume_ratio_30"] > 1.2)
```

---

## Pseudocode Spec

### `emit_condition(node) -> str`

The coding agent implements this pseudocode in Python. No algorithmic decisions are left to the coding agent — only translation.

```
function emit_condition(node: dict) -> str:
    """
    Preconditions (enforced by the validator before this is called):
      - node["type"] is one of "condition", "AND", "OR"
      - All leaf nodes: "left" is str, "op" is in allowed set, "right" is str or number
      - All group nodes: "children" is a list with at least one element
      - All column names exist in the indicator catalogue
    """

    if node["type"] == "condition":
        # Base case: leaf node — emit a single comparison expression

        left_expr = format_column_ref(node["left"])

        right = node["right"]
        if isinstance(right, (int, float)):
            # Scalar constant: emit as Python literal
            # If float is integer-valued (e.g. 30.0), emit as int (30) for cleaner code
            if isinstance(right, float) and right == int(right):
                right_expr = str(int(right))
            else:
                right_expr = repr(right)
        else:
            # str: column reference
            right_expr = format_column_ref(right)

        return f"{left_expr} {node['op']} {right_expr}"

    elif node["type"] in ("AND", "OR"):
        # Recursive case: group node — emit each child and join

        connector = " and " if node["type"] == "AND" else " or "

        child_exprs = []
        for child in node["children"]:
            child_exprs.append(emit_condition(child))   # ← recursive call

        joined = connector.join(child_exprs)
        return f"({joined})"

    else:
        raise ValueError(f"emit_condition: unknown node type '{node['type']}'")


function format_column_ref(col_name: str) -> str:
    # Produces: df.iloc[-2]["col_name"]
    return f'df.iloc[-2]["{col_name}"]'
```

### Integration point in the generated strategy

The emitter is called by the generator (TASK-014c / TASK-017) to produce the `buy_expr` and `sell_expr` strings. The generator embeds them verbatim:

```
function generate_get_last_signal(buy_condition_node, sell_condition_node) -> str:
    buy_expr  = emit_condition(buy_condition_node)
    sell_expr = emit_condition(sell_condition_node)

    return f"""
def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    if {buy_expr}:
        return "buy"
    elif {sell_expr}:
        return "sell"
    return "none"
"""
```

If the buy expression is a single leaf node (no AND/OR wrapper), `emit_condition` returns an unwrapped expression like `df.iloc[-2]["rsi_14"] < 30`. This is valid Python for an `if` statement — no change needed. If the buy expression is a group node, it returns `(...)` — also valid.

---

## Edge Cases — Enumerated with Prescribed Handling

### EC-1: Empty children list (`"children": []`)

**When it occurs**: Bug in the GUI serializer, or a user-created group with no conditions.

**Prescribed handling**: Caught by the **validator** at save time. The validator rejects any tree containing a group node with fewer than 2 children and returns an error to the GUI before the generator is called. The emitter never receives an empty-children node — this is a precondition violation. The emitter raises `ValueError` as a defensive check but should never reach that branch in normal operation.

**Rationale**: An empty AND node would emit `()`, which is invalid Python. An empty OR node would emit `()` equally. Do not silently emit `True` — that would cause the strategy to always buy or always sell, which is a dangerous silent failure.

---

### EC-2: Single-child group (`"children": [X]`)

**When it occurs**: A user creates a group and fills only one condition, then saves.

**Prescribed handling**: The **validator** warns the user in the GUI ("A group must contain at least 2 conditions"). The save action is blocked until corrected. The emitter handles it gracefully if it somehow reaches execution: a single-child AND/OR emits `(child_expr)` — syntactically valid Python, semantically a no-op grouping. No special-casing in the emitter.

**Rationale**: Defensively correct in the emitter; strictly validated in the GUI. This split is intentional — the emitter should be a reliable tool even in test/debug scenarios where the validator is bypassed.

---

### EC-3: Conflicting buy/sell conditions (same tree on both sides)

**When it occurs**: User sets the buy condition tree equal to the sell condition tree (same structure and values).

**Prescribed handling**: The **validator** compares `json.dumps(buy_condition, sort_keys=True)` with `json.dumps(sell_condition, sort_keys=True)`. If they are identical, the GUI shows a warning: "Buy and sell conditions are identical — the strategy will always trade buy." The user may save anyway (it may be intentional for testing), but the warning is shown. The emitter is uninvolved — it does not know whether it is emitting a buy or sell condition.

**Runtime behavior** (for completeness, not emitter concern): `get_last_signal` checks buy first. If buy and sell conditions are both true simultaneously (structurally identical conditions evaluated on the same `df.iloc[-2]`), the function returns `"buy"`. This is correct by the first-branch semantics of `if/elif`.

---

### EC-4: Maximum nesting depth

**Technical limit**: Python's default recursion limit is 1000. A 1000-level-deep condition tree would hit the Python stack limit, but this is not a realistic concern — no trading strategy has 1000 levels of logical nesting.

**Recommended GUI limit**: 5 levels of nesting. Beyond 5 levels, the condition is unreadable to a human and likely represents a user error. The GUI combinator should visually prevent adding a new sub-group when the current depth is already 5.

**Emitter behavior**: The emitter does not enforce depth limits. Depth enforcement is the GUI's responsibility. If the emitter receives a 10-level-deep tree, it handles it correctly — it simply recurses 10 levels deep, well within Python's safe range.

---

### EC-5: Scalar integer vs. float formatting

**Issue**: JSON does not distinguish `int` from `float`. `30` parses as Python `int`; `30.0` parses as Python `float`. In Python source code, `30` and `30.0` are both valid, but `30` is cleaner for integer-valued constants (e.g., RSI thresholds, Supertrend direction).

**Prescribed handling** (in emitter pseudocode above):
```
if isinstance(right, float) and right == int(right):
    right_expr = str(int(right))   # 30.0 → "30"
else:
    right_expr = repr(right)       # 1.5 → "1.5"
```

**Rationale**: Generated code reads as `rsi_14 < 30`, not `rsi_14 < 30.0`. This is a cosmetic concern — both are numerically correct — but clean generated code is easier to debug.

---

### EC-6: Operator injection via `op` field

**Issue**: The `op` field is embedded directly into the generated Python source code string. If an attacker (or a bug) injects arbitrary code into `op`, the generated strategy file becomes malicious.

**Prescribed handling**: The validator enforces that `op` is exactly one of `{"<", ">", "<=", ">=", "==", "!="}` before the generator is called. The emitter does not re-validate the operator — it trusts the precondition. However, as a defense-in-depth measure, the generator (TASK-017) should include a final `ast.parse` check on the entire generated file before writing it to disk. If `ast.parse` raises `SyntaxError`, the file is not written and an error is returned to the GUI.

---

### EC-7: Column name with special characters

**Issue**: Column names are used inside `df.iloc[-2]["col_name"]` as string literals. If a column name contains a double quote, the generated code would be syntactically broken.

**Assessment**: All column names in the TASK-014a catalogue are composed of alphanumeric characters and underscores (e.g., `ema_9`, `bb_upper_20`, `supertrend_dir`). No column name contains a double quote or any other special character that would cause issues inside a Python string literal.

**Prescribed handling**: The validator confirms at save time that all referenced column names are in the catalogue. Since the catalogue only contains safe names, this implicitly prevents injection. No additional escaping is needed in the emitter. If future indicators introduce column names with special characters, the emitter should be updated to use `json.dumps(col_name)` instead of f-string interpolation for the string literal.

---

### EC-8: `right` is a string that looks like a number (e.g., `"30"`)

**Issue**: JSON `"30"` (string) parses as Python `str`, but the user may have intended a scalar.

**Assessment**: This cannot occur in normal GUI operation — the GUI form fields are type-constrained (number inputs for scalars, dropdown selectors for column names). If a scalar threshold input emits `"30"` instead of `30`, that is a GUI bug. The emitter would interpret it as a column reference and emit `df.iloc[-2]["30"]`, which would raise a `KeyError` at runtime.

**Prescribed handling**: Validator checks that all `right` values of type `str` are in the indicator catalogue. If `"30"` (a string) does not match any column name, the validator rejects it with an error. The validator does NOT silently coerce `"30"` → `30` — it is an error that must be fixed in the GUI.

---

## Confirmation / Revision of context.md Recommendation

**Verdict**: **Confirmed** with one explicit addition.

The context.md recommended structure:
```json
{
  "type": "OR",
  "children": [
    {
      "type": "AND",
      "children": [
        {"type": "condition", "left": "rsi", "op": "<", "right": 30},
        {"type": "condition", "left": "close", "op": ">", "right": "ema_20"}
      ]
    },
    ...
  ]
}
```

This is structurally correct and is adopted verbatim. The **one addition** is making explicit the `right` field type discrimination rule, which the context.md example uses implicitly:

> **Rule (normative)**: In a `ConditionLeaf` node, `right` is a JSON **number** to represent a scalar constant, and a JSON **string** to represent a column name reference. This is not a convention — it is the data model's type system. The emitter checks `isinstance(right, (int, float))` to branch between the two cases.

The context.md also used simplified column names (`"rsi"`, `"ema_20"`). Per TASK-014a, the canonical names are `"rsi_14"`, `"ema_9"`, etc. The structure is identical; only the values change.

No structural revision to the recommended tree model.

---

## Sub-Team Assessment

**Question**: Does the condition engine scope warrant a dedicated sub-team brief to Jarvis before TASK-015 is assigned?

**Assessment**: **No dedicated sub-team needed.**

The condition engine consists of:
1. The `ConditionNode` data model — **fully specified in this document**
2. The recursive emitter (`emit_condition`) — **pseudocode fully specified in this document**
3. The validator (structural validation before generation) — a straightforward function checking node types, operator values, and column name membership; approximately 30–40 lines of Python
4. The emitter implementation — approximately 30–40 lines of Python; one well-scoped sub-function inside `strategies/builder.py` (TASK-017)

Total condition engine implementation: ~70–80 lines across two functions (validator + emitter), both in `strategies/builder.py`. This is not large enough to warrant a dedicated agent or sub-team. TASK-017's implementation task covers it naturally as part of the generator work.

Jarvis may assign TASK-015 to Grace without waiting for a sub-team assessment — the condition tree model is fully specified.

---

## Summary of Deliverables for TASK-014c

TASK-014c may now build on the following settled decisions from this spec:

1. **`ConditionNode` JSON schema** — formally defined above; `ConditionLeaf` and `ConditionGroup` as discriminated union on `type`
2. **`right` operand typing** — JSON number → scalar; JSON string → column reference; no extra fields
3. **N-ary tree** — `children` array, not binary left/right
4. **`emit_condition` pseudocode** — recursive descent; base case and recursive case both specified
5. **Emitter output format** — `df.iloc[-2]["col"]` for column refs; Python literal for scalars; parentheses around every AND/OR group
6. **Edge case handling contracts** — EC-1 through EC-8 all prescribed; the validator is the gatekeeper; the emitter assumes pre-validated input
7. **8 edge cases** — all prescribed with handling decisions; no open questions remain

---

## Addendum (TASK-019, 2026-04-08): Crossover Conditions and the ConditionNode Model

This addendum records the decision made in TASK-019 regarding multi-candle crossover conditions. The full rationale is in `agents/specs/TASK-019-adx-di-crossover-spec.md`.

### Problem

The `primeraEstrategia.md` strategy requires "+DI crosses above -DI" as a buy trigger. This is an inherently multi-row condition: it compares two consecutive candles. The current `ConditionNode` model emits `df.iloc[-2]["col"]` — single-row access only.

Three options were considered in TASK-019:

| Option | Description | ConditionNode impact |
|--------|-------------|----------------------|
| A | New `"crossover"` node type | Schema change, validator change, both emitters change |
| B | Pre-computed boolean column in `prepare_dataframe` | **Zero changes to schema or emitters** |
| C | `row` offset field on `ConditionLeaf` | Schema change, both emitters change |

### Decision: Option B selected

**The ConditionNode model is unchanged.** Crossover conditions are represented as pre-computed integer columns (0/1) in `prepare_dataframe`. The Builder emits them as standard leaf conditions:

```json
{"type": "condition", "left": "plus_di_cross_14", "op": ">", "right": 0}
```

Which produces (via `emit_condition`, unchanged):
```python
df.iloc[-2]["plus_di_cross_14"] > 0
```

### Rule for future crossover indicators

Any indicator that introduces a crossover or state-transition condition must pre-compute a boolean flag column in `prepare_dataframe`. The naming convention is `<source_col>_cross_<period>` (e.g., `plus_di_cross_14`). The ConditionNode model does **not** need to be extended to support multi-row conditions — that complexity stays in the indicator's helper function.

This is the established pattern: `supertrend_dir`, `tci_hist` are pre-computed state columns used as condition operands. Crossover flags follow the same pattern.
