#!/bin/bash
# PostToolUse hook: fires after every Write/Edit.
# Only acts if the edited file is agents/tasks.md.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/hook.log"
TASKS_FILE="$SCRIPT_DIR/../../agents/tasks.md"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" \
  2>/dev/null || echo "")

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) hook fired | file=$FILE_PATH | pid=$$" >> "$LOG"

FILE_PATH_NORM="${FILE_PATH//\\//}"
if [[ "$FILE_PATH_NORM" == *"agents/tasks.md"* ]]; then
  if [[ -f "$TASKS_FILE" ]] && grep -qiE '<!--[[:space:]]*hook-permission[[:space:]]*:[[:space:]]*ON[[:space:]]*-->' "$TASKS_FILE"; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) dispatching..." >> "$LOG"
    python "$SCRIPT_DIR/dispatch.py" >> "$LOG" 2>&1 &
  else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) hook permission OFF; skipping dispatch." >> "$LOG"
  fi
fi

exit 0
