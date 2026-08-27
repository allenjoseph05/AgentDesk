#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIRECTORY}/.." && pwd)"
COMPOSE_FILES=(
  -f compose.yaml
  -f compose.demo.yaml
  -f compose.codespaces.yaml
)

cd "${REPOSITORY_ROOT}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command is unavailable: $1" >&2
    exit 1
  fi
}

compose() {
  docker compose "${COMPOSE_FILES[@]}" "$@"
}

print_access_instructions() {
  local public_url=""
  if [[ -n "${CODESPACE_NAME:-}" ]]; then
    public_url="https://${CODESPACE_NAME}-5173.app.github.dev"
  fi

  echo
  echo "AgentDesk is healthy on port 5173."
  echo "In the Codespaces PORTS tab, set port 5173 visibility to Public."
  if [[ -n "${public_url}" ]]; then
    echo "Then open: ${public_url}"
  fi
  echo "Coordinator and specialist ports are not published by this Compose profile."
}

require_command docker

case "${1:-up}" in
  up)
    docker compose version >/dev/null
    compose config --quiet
    compose up --build --wait
    print_access_instructions
    ;;
  stop)
    compose down
    ;;
  status)
    compose ps
    ;;
  logs)
    shift
    compose logs --no-color "$@"
    ;;
  *)
    echo "Usage: bash scripts/codespaces_demo.sh [up|stop|status|logs [service...]]" >&2
    exit 2
    ;;
esac
