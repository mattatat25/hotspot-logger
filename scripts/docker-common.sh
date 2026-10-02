#!/usr/bin/env bash
# Shared by setup, backup, restore, and update. Source this file from Bash.

choose_docker() {
  DOCKER=(docker)
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not installed. Run bash setup.sh first." >&2
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    if [[ $EUID -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
      echo "Docker needs administrator access. Enter your Linux password if asked." >&2
      DOCKER=(sudo docker)
    fi
    if ! "${DOCKER[@]}" info >/dev/null; then
      echo "Docker is not running or is not accessible. See docs/TROUBLESHOOTING.md." >&2
      return 1
    fi
  fi
  if ! "${DOCKER[@]}" compose version >/dev/null 2>&1; then
    echo "The Docker Compose plugin is missing. See docs/INSTALL.md." >&2
    return 1
  fi
}

start_logger() {
  if ! "${DOCKER[@]}" compose up --help | grep -q -- '--wait-timeout'; then
    echo "Update Docker Compose to a version with --wait-timeout, then try again." >&2
    return 1
  fi
  if ! "${DOCKER[@]}" compose up -d --build --wait --wait-timeout 120 logger; then
    echo "The logger did not become healthy. Recent logs:" >&2
    "${DOCKER[@]}" compose logs --tail=50 logger >&2 || true
    return 1
  fi
}
