"""
tests/test_dispatch.py — unit tests for the auto-launch hook gate.

Run with: python tests/test_dispatch.py
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parent.parent
DISPATCH_PATH = ROOT / ".claude" / "hooks" / "dispatch.py"


def load_dispatch_module():
    spec = importlib.util.spec_from_file_location("dispatch_module", DISPATCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_tasks_md(permission):
    return """# Task Backlog

<!-- hook-permission: {permission} -->

## Active / Todo

### TASK-001: Example

- **ID**: TASK-001
- **Priority**: P1
- **Status**: todo
- **Assigned**: Grace
- **Blocked by**: nada
""".format(permission=permission)


class FakeTasksFile:
    def __init__(self, text):
        self._text = text

    def exists(self):
        return True

    def read_text(self, encoding="utf-8"):
        return self._text


class DispatchPermissionTests(unittest.TestCase):
    def setUp(self):
        self.dispatch = load_dispatch_module()

    def test_hook_permission_enabled_only_when_on(self):
        self.assertTrue(self.dispatch.hook_permission_enabled("<!-- hook-permission: ON -->"))
        self.assertFalse(self.dispatch.hook_permission_enabled("<!-- hook-permission: OFF -->"))
        self.assertFalse(self.dispatch.hook_permission_enabled("# no flag"))

    def test_main_skips_launch_when_permission_is_off(self):
        original_tasks_file = self.dispatch.TASKS_FILE
        original_load_running = self.dispatch.load_running
        original_save_running = self.dispatch.save_running
        original_open_terminal = self.dispatch.open_terminal

        launch_calls = []

        try:
            self.dispatch.TASKS_FILE = FakeTasksFile(make_tasks_md("OFF"))
            self.dispatch.load_running = lambda: {}
            self.dispatch.save_running = lambda data: None
            self.dispatch.open_terminal = lambda *args: launch_calls.append(args) or 123
            self.dispatch.main()
        finally:
            self.dispatch.TASKS_FILE = original_tasks_file
            self.dispatch.load_running = original_load_running
            self.dispatch.save_running = original_save_running
            self.dispatch.open_terminal = original_open_terminal

        self.assertEqual(launch_calls, [])

    def test_main_launches_when_permission_is_on(self):
        original_tasks_file = self.dispatch.TASKS_FILE
        original_load_running = self.dispatch.load_running
        original_save_running = self.dispatch.save_running
        original_open_terminal = self.dispatch.open_terminal

        launch_calls = []

        try:
            self.dispatch.TASKS_FILE = FakeTasksFile(make_tasks_md("ON"))
            self.dispatch.load_running = lambda: {}
            self.dispatch.save_running = lambda data: None
            self.dispatch.open_terminal = lambda *args: launch_calls.append(args) or 123
            self.dispatch.main()
        finally:
            self.dispatch.TASKS_FILE = original_tasks_file
            self.dispatch.load_running = original_load_running
            self.dispatch.save_running = original_save_running
            self.dispatch.open_terminal = original_open_terminal

        self.assertEqual(len(launch_calls), 1)
        self.assertEqual(launch_calls[0][0], "TASK-001")
        self.assertEqual(launch_calls[0][1], "grace")


if __name__ == "__main__":
    unittest.main()
