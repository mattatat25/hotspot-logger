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

current_branch=$(git branch --show-current)
if [[ -z "$current_branch" ]]; then
  echo "This checkout is not on a branch. Switch to a branch before updating." >&2
  exit 1
fi

bash scripts/backup.sh
git fetch --prune origin main

if ! git merge-base --is-ancestor HEAD origin/main; then
  echo "This branch cannot be updated safely with a fast-forward." >&2
  echo "See docs/BACKUP-AND-UPDATES.md under 'Repair an older beta checkout'." >&2
  exit 1
fi

git merge --ff-only origin/main
git config "branch.${current_branch}.remote" origin
git config "branch.${current_branch}.merge" refs/heads/main
bash setup.sh
