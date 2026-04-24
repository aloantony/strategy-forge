"""
dispatch.py — Auto-launcher de agentes basado en agents/tasks.md.

Ejecutado por task_watcher.sh cada vez que tasks.md es editado.
Solo lanza terminales si agents/tasks.md contiene el flag:
<!-- hook-permission: ON -->
Lee el estado actual, aplica las reglas de conflicto del sprint y abre
una nueva ventana de terminal por cada agente que queda desbloqueado.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = (SCRIPT_DIR / ".." / "..").resolve()
TASKS_FILE = PROJECT_ROOT / "agents" / "tasks.md"
RUNNING_FILE = SCRIPT_DIR / "running.json"
PROMPTS_DIR = SCRIPT_DIR / "prompts"
PROMPTS_DIR.mkdir(exist_ok=True)

# Map assigned name → agent definition file
AGENT_FILES = {
    "grace":  "agents/grace.md",
    "felix":  "agents/felix.md",
    "daniel": "agents/daniel.md",
    "jarvis":  ".claude/agents/jarvis.md",
}

HOOK_PERMISSION_RE = re.compile(
    r"<!--\s*hook-permission\s*:\s*(on|off)\s*-->",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# tasks.md sync helper
# ---------------------------------------------------------------------------

def _sync_status_in_tasks_md(task_id: str, new_status: str) -> None:
    """Actualiza el status de task_id en tasks.md cuando el task file difiere."""
    try:
        text = TASKS_FILE.read_text(encoding="utf-8")
        pattern = (
            r"(\|\s*\[{id}\]\(tasks/{id}\.md\)\s*\|\s*)"
            r"(?:todo|in-progress|done)"
            r"(\s*\|)"
        ).format(id=re.escape(task_id))
        new_text = re.sub(pattern, r"\g<1>{}\2".format(new_status), text, count=1)
        if new_text != text:
            TASKS_FILE.write_text(new_text, encoding="utf-8")
            print("[dispatch] Synced {} -> {} in tasks.md".format(task_id, new_status))
    except Exception as e:
        print("[dispatch] WARN: could not sync {} to tasks.md: {}".format(task_id, e))


# ---------------------------------------------------------------------------
# Parse tasks.md
# ---------------------------------------------------------------------------

def parse_tasks(text):
    """Parse the compact index table in tasks.md.

    Expected table row format (Active section):
        | [TASK-019](tasks/TASK-019.md) | done | Daniel | — | TASK-025 |

    Columns: ID (with optional markdown link), Status, Assigned, Blocked by, Blocks.
    Rows in the Completed section are ignored (agents don't need to launch them).
    """
    tasks = []
    in_active = False
    in_completed = False

    for line in text.splitlines():
        if re.match(r"^##\s+Active", line, re.IGNORECASE):
            in_active = True
            in_completed = False
            continue
        if re.match(r"^##\s+Completed", line, re.IGNORECASE):
            in_active = False
            in_completed = True
            continue

        if not in_active:
            continue

        # Match table data rows (skip header and separator rows)
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        # Skip header row and separator row
        if cells[0].startswith("-") or cells[0].lower().startswith("id"):
            continue

        # Extract TASK-ID from possible markdown link: [TASK-019](tasks/TASK-019.md)
        id_cell = cells[0]
        m = re.search(r"(TASK-\d+[a-z]*)", id_cell)
        if not m:
            continue
        task_id = m.group(1)

        status   = cells[1].strip().lower()
        assigned = cells[2].strip().lower()
        blocked_raw = cells[3].strip()
        blocks_raw  = cells[4].strip()

        blocked_by = re.findall(r"TASK-\d+[a-z]*", blocked_raw)
        blocks     = re.findall(r"TASK-\d+[a-z]*", blocks_raw)

        # Read title and authoritative status from the individual task file if it exists
        task_file = PROJECT_ROOT / "agents" / "tasks" / "{}.md".format(task_id)
        title = task_id  # fallback
        if task_file.exists():
            for i, line in enumerate(task_file.read_text(encoding="utf-8").splitlines()):
                if i == 0:
                    m2 = re.match(r"^#\s+TASK-\d+[a-z]*:\s*(.*)", line)
                    if m2:
                        title = m2.group(1).strip()
                m_status = re.match(r"^\s*-\s*\*\*Status\*\*:\s*(\S+)", line)
                if m_status:
                    file_status = m_status.group(1).strip().lower()
                    if file_status == "done" and status != "done":
                        print("[dispatch] {} task file says done but tasks.md says {} — treating as done".format(task_id, status))
                        status = "done"
                        _sync_status_in_tasks_md(task_id, "done")
                    break

        tasks.append({
            "id": task_id,
            "title": title,
            "status": status,
            "assigned": assigned,
            "blocked_by": blocked_by,
            "blocks": blocks,
        })

    return tasks


def hook_permission_enabled(text):
    """Return True only when tasks.md explicitly grants hook permission."""
    match = HOOK_PERMISSION_RE.search(text)
    return bool(match and match.group(1).upper() == "ON")


# ---------------------------------------------------------------------------
# running.json helpers
# ---------------------------------------------------------------------------

def load_running():
    if not RUNNING_FILE.exists():
        return {}
    try:
        return json.loads(RUNNING_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_running(data):
    RUNNING_FILE.write_text(json.dumps(data, indent=2))


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError, TypeError):
        return False


def clean_completed_tasks(running, task_map):
    """Remove entries only for tasks that are done or removed from the backlog.

    running.json is a 'dispatched but not finished' registry. Entries are kept
    until the task is marked done in tasks.md — NOT based on launcher PID liveness.
    The launcher PID (wt.exe / cmd.exe) dies seconds after opening the terminal,
    so pid_alive() would wrongly evict entries for tasks still in progress.
    """
    cleaned = {}
    for task_id, info in running.items():
        status = task_map.get(task_id, {}).get("status", "")
        if status == "done":
            print("[dispatch] {} is done — removing from running.json".format(task_id))
            continue
        if task_id not in task_map:
            print("[dispatch] {} not in tasks.md — removing from running.json".format(task_id))
            continue
        cleaned[task_id] = info
        if not pid_alive(info.get("pid", 0)):
            print("[dispatch] {} PID dead but task not done — keeping entry to prevent re-launch".format(task_id))
    return cleaned


# ---------------------------------------------------------------------------
# Build prompt
# ---------------------------------------------------------------------------

def build_prompt(task):
    assigned = task["assigned"]
    agent_file = AGENT_FILES.get(assigned, "agents/{}.md".format(assigned))
    task_file = "agents/tasks/{}.md".format(task["id"])
    task_file_path = PROJECT_ROOT / task_file
    if task_file_path.exists():
        task_ref = (
            "Your task detail (description, files to read, acceptance criteria) "
            "is in {task_file} — read that file for everything you need. "
            "agents/tasks.md is a compact index only; do not read it for task details."
        ).format(task_file=task_file)
    else:
        task_ref = (
            "Read agents/context.md for project context and agents/tasks.md for the task backlog. "
            "Execute task {task_id}: {title}."
        ).format(task_id=task["id"], title=task["title"])
    return (
        "You are {name}, a specialized agent for the trading-agent project. "
        "Read {agent_file} for your complete role definition and workflow. "
        "{task_ref} "
        "Follow your role definition exactly. "
        "When updating task status (to in-progress or done): update ONLY your task file "
        "agents/tasks/{task_id}.md — change the '- **Status**: ...' line using the Edit tool. "
        "Do NOT edit agents/tasks.md — it is updated by Jarvis only. "
        "Editing tasks.md from agent sessions causes file-conflict errors when multiple agents run in parallel."
    ).format(
        name=assigned.capitalize(),
        agent_file=agent_file,
        task_ref=task_ref,
        task_id=task["id"],
    )


# ---------------------------------------------------------------------------
# Open terminal
# ---------------------------------------------------------------------------

def open_terminal(task_id, assigned, prompt):
    """Open a new visible terminal running claude -p. Returns launcher PID."""
    prompt_file = PROMPTS_DIR / "{}.txt".format(task_id)
    prompt_file.write_text(prompt, encoding="utf-8")

    # Write a proper .sh script — avoids all quoting hell with -c strings
    proj = str(PROJECT_ROOT).replace("\\", "/")
    prompt_path = str(prompt_file).replace("\\", "/")
    script_file = PROMPTS_DIR / "{}_launch.sh".format(task_id)
    script_file.write_text(
        "#!/bin/bash\n"
        "cd \"{proj}\"\n"
        "PROMPT=$(cat \"{prompt_path}\")\n"
        "claude \"$PROMPT\"\n"
        "echo \"\"\n"
        "echo \"=== Sesion {task_id} terminada ===\"\n"
        "read -p \"Pulsa Enter para cerrar...\"\n".format(
            proj=proj, prompt_path=prompt_path, task_id=task_id
        ),
        encoding="utf-8",
    )

    title = "{}: {}".format(task_id, assigned.capitalize())
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    script_path = str(script_file).replace("\\", "/")

    # Try Windows Terminal (wt) with Git Bash running the script
    try:
        proc = subprocess.Popen(
            ["wt", "new-tab", "--title", title, "--", git_bash, script_path],
            cwd=str(PROJECT_ROOT),
        )
        return proc.pid
    except FileNotFoundError:
        pass

    # Fallback: cmd start
    proc = subprocess.Popen(
        ["cmd", "/c", "start", title, git_bash, script_path],
        cwd=str(PROJECT_ROOT),
    )
    return proc.pid


# ---------------------------------------------------------------------------
# Main dispatch logic
# ---------------------------------------------------------------------------

def main():
    if not TASKS_FILE.exists():
        return

    text = TASKS_FILE.read_text(encoding="utf-8")
    if not hook_permission_enabled(text):
        print("[dispatch] Hook permission is OFF in agents/tasks.md.")
        return

    tasks = parse_tasks(text)
    task_map = {t["id"]: t for t in tasks}

    running = clean_completed_tasks(load_running(), task_map)
    save_running(running)
    launched_any = False

    for task in tasks:
        task_id = task["id"]
        status = task["status"]
        assigned = task["assigned"].lower()

        if status != "todo":
            continue

        # Rule 1 — all blockers must be done
        blockers_done = all(
            task_map.get(b, {}).get("status") == "done"
            for b in task["blocked_by"]
        )
        if not blockers_done:
            continue

        # Rule 5 — same agent already running
        agent_busy = any(
            info.get("assigned", "").lower() == assigned
            for info in running.values()
        )
        if agent_busy:
            continue

        # Already tracked as running
        if task_id in running:
            continue

        prompt = build_prompt(task)
        try:
            pid = open_terminal(task_id, assigned, prompt)
        except Exception as e:
            print("[dispatch] ERROR launching {}: {}".format(task_id, e), file=sys.stderr)
            continue

        running[task_id] = {
            "pid": pid,
            "assigned": assigned,
            "started": datetime.now(timezone.utc).isoformat(),
        }
        save_running(running)
        launched_any = True
        print("[dispatch] Launched {} ({}) — PID {}".format(task_id, assigned, pid))

    if not launched_any:
        print("[dispatch] No new tasks to launch.")


if __name__ == "__main__":
    main()
