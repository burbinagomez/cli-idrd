#!/usr/bin/env bash
# Per-task: kanban record (backend-assigned) + git branch. Usage: ./create-task.sh "<TITLE>" <SLUG>
set -euo pipefail
TITLE="${1:?title}"; SLUG="${2:?slug}"
BR="task/${SLUG}"
hermes kanban create --assignee backend --workspace worktree --branch "${BR}" "${TITLE}" --json
if git rev-parse --verify "${BR}" >/dev/null 2>&1; then
  echo "git branch ${BR} already present"
else
  git branch "${BR}" && echo "git branch ${BR} created"
fi
