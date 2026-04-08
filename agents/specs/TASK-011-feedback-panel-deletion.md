# GUI Change Spec: Feedback Panel Deletion

**By**: Grace
**Date**: 2026-04-02
**Task**: TASK-011
**Status**: ready

---

## Summary

This spec identifies every line range, method, CSS rule, JS block, and import that exists solely to support the feedback panel in `gui_charts.py`. With `feedback_server.py` deleted and all `FEEDBACK_*` config variables removed (TASK-001, TASK-003), this code is unreachable dead weight. The deletion is safe to execute now. There are no shared helpers — every symbol identified below is exclusively feedback-specific. Felix must delete exactly what is listed and nothing else.

---

## Affected Methods

| Method | File location (approx line) | Change type | Threading context |
|--------|---------------------------|-------------|-------------------|
| `_inject_custom_styles` | ~1615 | modify (remove CSS block) | main |
| `setup_side_panel` | ~2957 | modify (remove feedback setup vars + simplify call) | main |
| `_build_side_panel` | ~2978 | modify (signature, payload keys, JS feedback panel DOM block, toolbar entry, activate fn) | main |
| `on_side_panel_event` | ~4209 | modify (remove two action branches) | main |
| `_handle_feedback_send` | ~4254 | delete entire method | main |
| `_save_feedback_local` | ~4291 | delete entire method | main |
| `_post_feedback_webhook` | ~4305 | delete entire method | main |
| `_get_feedback_list_url` | ~4323 | delete entire method | main |
| `_handle_feedback_list` | ~4343 | delete entire method | main |
| `_set_feedback_list` | ~4380 | delete entire method | main |
| `_set_feedback_status` | ~4456 | delete entire method | main |

---

## New Instance Variables (if any)

None. The `_feedback_list_404_seen` flag is never initialized in `__init__` — it only exists lazily inside `_handle_feedback_list` via `getattr(self, "_feedback_list_404_seen", False)`. It disappears automatically when that method is deleted; no `__init__` cleanup is needed.

---

## Threading Analysis

All affected methods run on the **main thread** (they are called from `on_side_panel_event`, which is registered as a pywebview event handler and is always called on the main thread). `_set_feedback_list` and `_set_feedback_status` both call `self.chart.run_script()` directly — this is allowed because they execute on the main thread.

**No threading concerns.** No `chart.run_script()` call from bot-loop or quote thread is involved.

---

## JavaScript Interaction Points

The feedback panel uses two JS→Python callbacks registered on the existing `side_panel_handler`:

- `payload.handler + "_~_feedback_send;;;" + subject + ";;;" + body` → dispatches to `on_side_panel_event` with `action == "feedback_send"`
- `payload.handler + "_~_feedback_list"` → dispatches to `on_side_panel_event` with `action == "feedback_list"`

Both of these callbacks originate inside the `feedbackPanel` JS DOM block and vanish when that DOM block is deleted. No handler registration needs to be explicitly un-registered — the Python `on_side_panel_event` function simply stops receiving these action strings.

No new JS interactions are introduced by this change.

---

## Insertion Point Map

### Site 1 — CSS block in `_inject_custom_styles`

**Location**: Inside the CSS f-string in `_inject_custom_styles`. Lines **2002–2110**.

**What changes**: Delete all 109 lines of `.tv-feedback-*` CSS class declarations.

**What must NOT change**:
- Line 2001 (`.tv-section-desc { ... }` closing `}`) — keep
- Line 2111 (`.tv-legacy-panel {` opening) — keep; this is the first non-feedback CSS class after the block

**Block to delete** (landmark: starts immediately after `.tv-section-desc { ... }` closing brace):
```
.tv-feedback-form { ... }
.tv-feedback-form input, .tv-feedback-form textarea { ... }
.tv-feedback-form textarea { ... }
.tv-feedback-form button { ... }
.tv-feedback-form button:hover { ... }
.tv-feedback-hint { ... }
.tv-feedback-status { ... }
.tv-feedback-status.success { ... }
.tv-feedback-status.error { ... }
.tv-feedback-actions { ... }
.tv-feedback-refresh { ... }
.tv-feedback-refresh:hover { ... }
.tv-feedback-list-status { ... }
.tv-feedback-list-status.success { ... }
.tv-feedback-list-status.error { ... }
.tv-feedback-list { ... }
.tv-feedback-item { ... }
.tv-feedback-item-title { ... }
.tv-feedback-item-message { ... }
.tv-feedback-item-meta { ... }
.tv-feedback-empty { ... }
```
(lines 2002–2110, ending at the `}` closing `.tv-feedback-empty`)

---

### Site 2 — `setup_side_panel`: feedback setup variables

**Location**: Lines **2965–2975** inside `setup_side_panel`.

**What changes**: Delete lines 2965–2974 (the five feedback-specific variable assignments), then simplify line 2975 from:
```python
self._build_side_panel(items, feedback_target, feedback_list_url)
```
to:
```python
self._build_side_panel(items)
```

**What must NOT change**:
- Lines 2957–2964 (handler registration and `items` setup) — keep
- Line 2976 (`self._render_strategy_panel()`) — keep

**Lines to delete (2965–2974)**:
```python
save_dir = getattr(config, "FEEDBACK_SAVE_DIR", "feedback") or "feedback"
webhook_url = (getattr(config, "FEEDBACK_WEBHOOK_URL", "") or "").strip()
if webhook_url:
    feedback_target = "Webhook"
else:
    feedback_target = f"Archivo local ({save_dir})"
feedback_list_url = ""
list_url_getter = getattr(self, "_get_feedback_list_url", None)
if callable(list_url_getter):
    feedback_list_url = list_url_getter()
```

---

### Site 3 — `_build_side_panel`: signature

**Location**: Line **2978**.

**What changes**: Remove the two feedback parameters from the method signature.

Before:
```python
def _build_side_panel(self, items, feedback_target: str, feedback_list_url: str):
```
After:
```python
def _build_side_panel(self, items):
```

**What must NOT change**: The method body beyond line 2978 is handled by later sites.

---

### Site 4 — `_build_side_panel`: payload dict feedback keys

**Location**: Lines **2992–2993** inside the `payload = json.dumps({...})` call.

**What changes**: Remove these two lines from the dict:
```python
"feedback_target": feedback_target or "Archivo local",
"feedback_list_url": feedback_list_url or "",
```

**What must NOT change**: All other payload keys (`items`, `icons`, `handler`, `strategies`, `selected_strategy`, `active_count`, `strategy_data_options`, `strategy_data_selected`, `strategy_data_all_actives`) must remain exactly as-is, including their trailing commas.

---

### Site 5 — `_build_side_panel`: feedbackPanel JS DOM creation block

**Location**: Lines **3021–3147** inside the `chart.run_script(f'''...''')` block.

**What changes**: Delete the entire feedback panel DOM construction block. This block starts at:
```javascript
const feedbackPanel = document.createElement("div");
feedbackPanel.id = "tv-feedback-panel";
```
(line 3021) and ends at:
```javascript
feedbackPanel.appendChild(listContainer);
```
(line 3147).

**What must NOT change**:
- Line 3020 (blank line after `newsPanel.innerHTML = ...`) — keep
- Line 3149 (`const legacyPanel = document.createElement("div");`) — keep

---

### Site 6 — `_build_side_panel`: `panel.appendChild(feedbackPanel)`

**Location**: Line **3418**.

**What changes**: Delete the single line:
```javascript
panel.appendChild(feedbackPanel);
```

**What must NOT change**:
- Line 3417 (`panel.appendChild(newsPanel);`) — keep
- Line 3419 (`panel.appendChild(legacyPanel);`) — keep

---

### Site 7 — `_build_side_panel`: toolbar `feedback` tool entry

**Location**: Lines **4172–4176** inside the `tools = [...]` array.

**What changes**: Delete the feedback entry object:
```javascript
{
    key: "feedback",
    label: "Sugerencias",
    icon: "<svg ...></svg>"
}}
```
(lines 4172–4176, including the surrounding `{{` / `}}` f-string escaped braces).

**What must NOT change**:
- Line 4171 (the closing `}},` of the `news` entry) — keep, but remove its trailing comma if it becomes the last entry
- The `legacy` and `news` entries must remain intact

**Note on trailing comma**: After removing the `feedback` entry, the `news` entry becomes the last item in the array. Its trailing comma (`,`) on line 4171 must be removed to keep valid JS syntax inside the f-string. The array becomes:
```javascript
const tools = [
    {{ key: "legacy", label: "Panel clásico", icon: "..." }},
    {{ key: "news", label: "Noticias", icon: "..." }}
];
```

---

### Site 8 — `_build_side_panel`: `feedbackLoaded` variable and `activate` function feedback branches

**Location**: Lines **4179** and **4183** and **4188–4191** inside the `activate` arrow function.

**What changes** (three surgical deletions):

1. Delete line **4179**:
   ```javascript
   let feedbackLoaded = false;
   ```
   (and the blank line 4180)

2. Delete line **4183**:
   ```javascript
   feedbackPanel.style.display = key === "feedback" ? "flex" : "none";
   ```

3. Delete lines **4188–4191**:
   ```javascript
   if (key === "feedback" && !feedbackLoaded) {{
       feedbackLoaded = true;
       requestList();
   }}
   ```

**What must NOT change**:
- Line 4181 (`const activate = (key) => {{`) — keep
- Line 4182 (`newsPanel.style.display = key === "news" ? ...`) — keep
- Line 4184 (`legacyPanel.style.display = key === "legacy" ? ...`) — keep
- Lines 4185–4187 (the `Object.keys(buttons).forEach(...)` block) — keep
- Line 4192 (`}};`) closing the activate function — keep

---

### Site 9 — `on_side_panel_event`: feedback action branches

**Location**: Lines **4212–4218** inside `on_side_panel_event`.

**What changes**: Delete the two `if action == "feedback_*"` blocks:
```python
if action == "feedback_send":
    subject = unquote(args[0]) if len(args) > 0 else ""
    message = unquote(args[1]) if len(args) > 1 else ""
    self._handle_feedback_send(subject, message)
    return
if action == "feedback_list":
    self._handle_feedback_list()
    return
```

**What must NOT change**: Line 4220 (`if action == "toggle" and args:`) — keep. This is the first live action handler.

---

### Site 10 — Seven feedback Python methods

**Location**: Lines **4254–4478** (from `def _handle_feedback_send` through the closing `''')` of `_set_feedback_status`).

**What changes**: Delete all seven methods in their entirety:

| Method | Approx start line | Approx end line |
|--------|-------------------|-----------------|
| `_handle_feedback_send` | 4254 | 4289 |
| `_save_feedback_local` | 4291 | 4303 |
| `_post_feedback_webhook` | 4305 | 4321 |
| `_get_feedback_list_url` | 4323 | 4341 |
| `_handle_feedback_list` | 4343 | 4378 |
| `_set_feedback_list` | 4380 | 4454 |
| `_set_feedback_status` | 4456 | 4478 |

**What must NOT change**: Line 4480 (`def _toggle_strategy_run(self):`) — this is the first live method after the feedback block and must not be touched.

Delete from line 4254 through line 4478 (inclusive), plus line 4479 (the blank separator line before `_toggle_strategy_run`). The blank line between `_toggle_strategy_run` and whatever precedes it will be provided by the blank line that naturally follows line 4253 (end of `on_side_panel_event`).

---

### Site 11 — Import cleanup

**Location**: Lines **25–27** at the top of the file.

**What changes**:

1. Delete line **25** entirely:
   ```python
   import urllib.error
   ```
   — `urllib.error` is only referenced in `_handle_feedback_list` (line 4360).

2. Delete line **26** entirely:
   ```python
   import urllib.request
   ```
   — `urllib.request` is only referenced in `_post_feedback_webhook` and `_handle_feedback_list`.

3. Modify line **27** — remove `urlparse` and `urlunparse`, keep `unquote`:
   Before:
   ```python
   from urllib.parse import unquote, urlparse, urlunparse
   ```
   After:
   ```python
   from urllib.parse import unquote
   ```
   — `urlparse` and `urlunparse` are only used in `_get_feedback_list_url`. `unquote` is used throughout `on_side_panel_event` for non-feedback actions and **must be kept**.

**What must NOT change**:
- Line 23 (`from datetime import datetime, timedelta, timezone`) — keep; `datetime` and `timezone` are used in equity chart and bot loop code; `timedelta` is used in equity chart rendering.
- Line 19 (`import os`) — keep; `os` is extensively used for strategy loading and file I/O outside feedback code.

---

## Shared Helpers Audit

The following symbols appear in the feedback methods but are **also used by live code** — they must NOT be deleted:

| Symbol | Used in feedback? | Used elsewhere? | Action |
|--------|------------------|-----------------|--------|
| `self.log_message` | yes (4283, 4302, etc.) | yes — throughout gui_charts.py | keep |
| `self.chart.run_script` | yes (_set_feedback_list, _set_feedback_status) | yes — throughout gui_charts.py | keep |
| `self.current_strategy_key` | yes (4266) | yes — strategy registry | keep |
| `self.current_timeframe` | yes (4267) | yes — chart update pipeline | keep |
| `getattr(config, ...)` pattern | yes | yes — throughout gui_charts.py | keep |
| `json.dumps` / `json` import | yes | yes — throughout gui_charts.py | keep |
| `os` module | yes (_save_feedback_local) | yes — strategy loading, file I/O | keep |
| `unquote` from urllib.parse | yes (action args decoding) | yes — all other on_side_panel_event branches | keep |
| `datetime`, `timezone`, `timedelta` | yes (4268) | yes — equity chart (5131, 5872, etc.) | keep |

---

## Invariant Checklist

- [x] No `chart.run_script()` from non-main-thread context — all feedback methods run on main thread; deletion has no threading impact
- [x] DOM elements use `getElementById` guard before creation — not applicable (deleting DOM creation, not adding)
- [x] New config accesses use `getattr(config, "KEY", default)` pattern — not applicable (no new config accesses)
- [x] New `self.*` variables initialized in `__init__` before first use — not applicable (no new variables; `_feedback_list_404_seen` is lazy and disappears with its method)
- [x] Strategy registry reads from bot-loop are read-only — this change does not touch strategy registry
- [x] Any new JS→Python handler name is unique — not applicable (removing handlers, not adding)
- [x] `_build_side_panel` sole caller is `setup_side_panel` — confirmed by grep; signature change is safe
- [x] `unquote` retained in import after removing `urlparse`/`urlunparse` — confirmed; `unquote` has live callers in `on_side_panel_event`
- [x] Trailing comma in JS `tools` array corrected after removing feedback entry — see Site 7 note
