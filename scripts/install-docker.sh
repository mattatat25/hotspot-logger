#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ! -r /etc/os-release ]] || ! command -v apt-get >/dev/null 2>&1; then
  echo "Automatic Docker installation supports Ubuntu, Debian, and 64-bit Raspberry Pi OS." >&2
  echo "For other systems, install Docker using https://docs.docker.com/engine/install/" >&2
  exit 1
fi
source /etc/os-release
platform_id=$ID
platform_release=${VERSION_CODENAME:-}
case "$platform_id:$platform_release" in
  ubuntu:jammy|ubuntu:noble|ubuntu:resolute|debian:bookworm|debian:trixie) ;;
  *) echo "Automatic installation does not support $PRETTY_NAME. See docs/INSTALL.md." >&2; exit 1 ;;
esac
architecture=$(dpkg --print-architecture)
case "$architecture" in
  amd64|arm64) ;;
  *) echo "Use a 64-bit OS (amd64 or arm64). For a Pi, install Raspberry Pi OS Lite (64-bit)." >&2; exit 1 ;;
esac

# Do not replace a container runtime that another application may be using.
for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc; do
  if [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true) == 'install ok installed' ]]; then
    echo "Found an existing container package: $package. No packages were changed." >&2
    echo "Follow Docker's $platform_id installation guide to resolve conflicting packages." >&2
    exit 1
  fi
done
if [[ -e /etc/apt/sources.list.d/docker.sources || -e /etc/apt/sources.list.d/docker.list ]]; then
  echo "A Docker package source already exists. Use the manual Docker instructions in docs/INSTALL.md." >&2
  exit 1
fi

ADMIN=()
if [[ $EUID -ne 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Administrator access is required. Install Docker as root, then rerun setup." >&2
    exit 1
  fi
  ADMIN=(sudo)
fi
"${ADMIN[@]}" apt-get update
"${ADMIN[@]}" apt-get install -y ca-certificates curl
"${ADMIN[@]}" install -m 0755 -d /etc/apt/keyrings
"${ADMIN[@]}" curl -fsSL --retry 3 "https://download.docker.com/linux/$platform_id/gpg" -o /etc/apt/keyrings/docker.asc
"${ADMIN[@]}" chmod a+r /etc/apt/keyrings/docker.asc
"${ADMIN[@]}" tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/$platform_id
Suites: $platform_release
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
EOF
"${ADMIN[@]}" apt-get update
"${ADMIN[@]}" apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
"${ADMIN[@]}" systemctl enable --now docker
