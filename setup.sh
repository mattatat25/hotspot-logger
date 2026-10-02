#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"
source scripts/docker-common.sh

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is needed to run Hotspot Logger."
  echo "Setup can install Docker Engine and Compose from Docker's official package repository."
  read -r -p "Install Docker on this computer? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES) bash scripts/install-docker.sh ;;
    *) echo "Install Docker first, then run bash setup.sh again. See docs/INSTALL.md."; exit 1 ;;
  esac
fi

choose_docker
start_logger

server_ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}' || true)
server_ip=${server_ip:-SERVER_IP}
printf '\nHotspot Logger is ready.\nOpen http://%s:8787 in your desktop or phone browser.\n\n' "$server_ip"
echo "Enter your callsign, hotspots, and optional QRZ key in the setup page."
echo "Your settings and contacts stay in the Docker data volume."
echo "Keep port 8787 on your trusted LAN; use a VPN for access away from home."
