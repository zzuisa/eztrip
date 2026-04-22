#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stop_port() {
  local port="$1"
  local label="$2"

  local pids
  pids="$(lsof -ti :"${port}" 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    echo "[INFO] ${label} not running on port ${port}."
    return 0
  fi

  echo "[INFO] Stopping ${label} on port ${port}: ${pids}"
  for pid in ${pids}; do
    kill "${pid}" >/dev/null 2>&1 || true
  done

  sleep 1

  local remain
  remain="$(lsof -ti :"${port}" 2>/dev/null || true)"
  if [[ -n "${remain}" ]]; then
    echo "[INFO] Force killing ${label} on port ${port}: ${remain}"
    for pid in ${remain}; do
      kill -9 "${pid}" >/dev/null 2>&1 || true
    done
  fi
}

stop_port 8881 "backend"
stop_port 5173 "frontend"

echo "[DONE] stop-dev completed."
