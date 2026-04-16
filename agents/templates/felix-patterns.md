# Felix — Coding Patterns Reference

Canonical patterns for `gui_charts.py`. Felix follows these exactly. No alternatives.

---

## Python → JS: simple script injection

```python
self.chart.run_script(f'''
    ;(function() {{
        // JS code here
        // use {{{{ }}}} for nested literal braces
        const value = {python_variable};
    }})();
''')
```

The IIFE wrapper `;(function() {{ ... }})();` is required for all top-level `run_script` injections.

---

## Python → JS: JSON payload pattern

Use whenever structured data crosses from Python to JS (more than two fields):

```python
payload = json.dumps({
    "key": value,
    "other_key": other_value,
})
self.chart.run_script(f'''
    ;(function() {{
        const payload = {payload};
        // payload.key, payload.other_key etc.
    }})();
''')
```

Safe from brace-escaping errors because JSON is serialized before the f-string is evaluated.

---

## JS → Python: callback registration

In Python (during setup):
```python
self._my_handler_name = 'my_handler_evt'
self.chart.win.handlers[self._my_handler_name] = self._on_my_event
```

In JS (invocation):
```javascript
window.callbackFunction(payload.handler + "_~_" + encodeURIComponent(arg1) + "_~_" + encodeURIComponent(arg2));
```

In Python (handler):
```python
def _on_my_event(self, action, *args):
    action = (action or "").strip()
    arg1 = unquote(args[0]) if len(args) > 0 else ""
    arg2 = unquote(args[1]) if len(args) > 1 else ""
    # handle
```

New actions go as new `if action == ...: return` branches — never `elif`.

---

## Thread-safe GUI updates from bot/quote threads

`chart.run_script()` may be called directly from any thread. Wrap in `try/except` to avoid crashing the bot loop:

```python
# From bot_loop, _quote_loop, or any method they call:
try:
    self.chart.run_script(f'...')
except Exception:
    pass
```

Note: `self._callback_queue` does NOT exist. Do not use it.

---

## Config access

```python
value = getattr(config, "CONFIG_KEY", default_value)
```

Never `config.KEY` directly for keys that may not exist.

---

## DOM idempotency guard

Any method that creates DOM elements and may be called more than once:

```javascript
let el = document.getElementById("my-element-id");
if (!el) {
    el = document.createElement("div");
    el.id = "my-element-id";
    // configure and append
} else {
    // update existing
}
```
