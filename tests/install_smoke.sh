#!/usr/bin/env bash
# Run only in the disposable Ubuntu/Debian container created by CI.
set -Eeuo pipefail
mkdir -p /tmp/install-test-bin
# Package installation is real; a disposable container has no systemd daemon.
printf '#!/bin/sh\nexit 0\n' > /tmp/install-test-bin/systemctl
chmod +x /tmp/install-test-bin/systemctl
export PATH="/tmp/install-test-bin:$PATH"
bash /source/scripts/install-docker.sh
docker --version
docker compose version
for package in docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; do
  test "$(dpkg-query -W -f='${Status}' "$package")" = 'install ok installed'
done
echo "Fresh Docker package installation passed on $(dpkg --print-architecture)."
