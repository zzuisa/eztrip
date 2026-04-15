#!/usr/bin/env bash
set -euo pipefail

# =========================================================
# Stop guardian-style backend + frontend processes
# Usage:
#   chmod +x stop-dev.sh
#   ./stop-dev.sh
# =========================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
BACKEND_PID_FILE="${LOG_DIR}/backend.pid"
FRONTEND_PID_FILE="${LOG_DIR}/frontend.pid"

stop_pid_file() {
  local pid_file="$1"
  local label="$2"

  if [[ ! -f "${pid_file}" ]]; then
    echo "[WARN] ${label} pid file not found: ${pid_file}"
    return 0
  fi

  local pid
  pid="$(tr -d '[:space:]' < "${pid_file}" || true)"
  if [[ -z "${pid}" ]]; then
    echo "[WARN] ${label} pid file is empty: ${pid_file}"
    return 0
  fi

  if kill -0 "${pid}" >/dev/null 2>&1; then
    echo "[INFO] Stopping ${label} (PID ${pid})..."
    kill "${pid}" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "${pid}" >/dev/null 2>&1; then
      echo "[WARN] ${label} still running, force killing PID ${pid}..."
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
  else
    echo "[INFO] ${label} already stopped (PID ${pid})."
  fi
}

stop_pid_file "${BACKEND_PID_FILE}" "backend"
stop_pid_file "${FRONTEND_PID_FILE}" "frontend"

echo "[DONE] Stop command finished."
