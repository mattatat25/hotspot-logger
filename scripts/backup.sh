#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

project_dir=$(cd "$(dirname "$0")/.." && pwd)
cd "$project_dir"
source scripts/docker-common.sh
choose_docker
mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
archive=$(mktemp "backups/hotspot-logger-$stamp-XXXXXX.tar.gz")
trap 'rm -f "$archive"' ERR

"${DOCKER[@]}" compose exec -T logger python - backup < maintenance.py > "$archive"

echo "Created $archive"
echo "This archive contains the QRZ key and password hash. Store it privately."
