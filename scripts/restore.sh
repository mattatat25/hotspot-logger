#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

if [[ $# != 1 || ! -f "$1" ]]; then
  echo "Usage: bash scripts/restore.sh backups/hotspot-logger-TIMESTAMP-SUFFIX.tar.gz" >&2
  exit 1
fi
archive=$(realpath "$1")
project_dir=$(cd "$(dirname "$0")/.." && pwd)
cd "$project_dir"
source scripts/docker-common.sh
choose_docker

"${DOCKER[@]}" compose build logger
staged_path=$("${DOCKER[@]}" compose run --rm --no-deps -T --entrypoint python logger maintenance.py stage-restore < "$archive")
trap '"${DOCKER[@]}" compose run --rm --no-deps -T --entrypoint python logger maintenance.py discard-staged "$staged_path" >/dev/null 2>&1 || true' EXIT

# Validate first; an invalid archive leaves the running service untouched.
"${DOCKER[@]}" compose stop logger
if ! "${DOCKER[@]}" compose run --rm --no-deps -T --entrypoint python logger maintenance.py restore "$staged_path"; then
  "${DOCKER[@]}" compose up -d logger
  echo "Restore failed. Check the logger and keep the backup before retrying." >&2
  exit 1
fi
start_logger

echo "Restored $archive"
echo "Sign in with the callsign and password saved in this backup."
