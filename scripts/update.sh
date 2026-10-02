#!/usr/bin/env bash
set -Eeuo pipefail

project_dir=$(cd "$(dirname "$0")/.." && pwd)
cd "$project_dir"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "This folder was downloaded as a ZIP. See docs/BACKUP-AND-UPDATES.md for ZIP updates." >&2
  exit 1
fi
if [[ -n $(git status --porcelain) ]]; then
  echo "This checkout has local changes. Commit or move them before updating." >&2
  git status --short
  exit 1
fi
bash scripts/backup.sh
git pull --ff-only
bash setup.sh
