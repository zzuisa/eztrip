#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${NOHUP_STARTED:-}" ]]; then
  export NOHUP_STARTED=1
  nohup "$0" "$@" >/dev/null 2>&1 &
  exit 0
fi

# =========================================================
# Guardian-style nohup startup script for backend + frontend
# Usage:
#   chmod +x start-dev.sh
#   nohup ./start-dev.sh >/dev/null 2>&1 &
# Optional:
#   export CONDA_BAT='D:/Anaconda3/condabin/conda.bat'
#   export PYTHON_BIN='python'
# =========================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"
LOG_DIR="${ROOT_DIR}/logs"
BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"
BACKEND_PID_FILE="${LOG_DIR}/backend.pid"
FRONTEND_PID_FILE="${LOG_DIR}/frontend.pid"

mkdir -p "${LOG_DIR}"

if [[ ! -d "${BACKEND_DIR}" ]]; then
  echo "[ERROR] Backend directory not found: ${BACKEND_DIR}"
  exit 1
fi

if [[ ! -d "${FRONTEND_DIR}" ]]; then
  echo "[ERROR] Frontend directory not found: ${FRONTEND_DIR}"
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python}"
UVICORN_CMD=("${PYTHON_BIN}" -m uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8881)
NPM_CMD=(npm run dev)

CONDA_BAT_PATH="${CONDA_BAT:-}"

start_backend() {
  echo "[INFO] Starting backend..."
  if [[ -n "${CONDA_BAT_PATH}" && -f "${CONDA_BAT_PATH}" ]]; then
    # Run backend detached via nohup -> cmd.exe /c ... so it survives terminal close.
    nohup cmd.exe /c "chcp 65001 >nul && call \"${CONDA_BAT_PATH}\" activate py310 && cd /d \"${BACKEND_DIR}\" && set PYTHONIOENCODING=utf-8 && ${UVICORN_CMD[*]}" >>"${BACKEND_LOG}" 2>&1 < /dev/null &
  else
    nohup bash -lc "cd \"${BACKEND_DIR}\" && export PYTHONIOENCODING=utf-8 && ${UVICORN_CMD[*]}" >>"${BACKEND_LOG}" 2>&1 < /dev/null &
  fi
  echo $! > "${BACKEND_PID_FILE}"
  echo "[INFO] Backend PID: $(cat "${BACKEND_PID_FILE}")"
}

start_frontend() {
  echo "[INFO] Starting frontend..."
  nohup bash -lc "cd \"${FRONTEND_DIR}\" && ${NPM_CMD[*]}" >>"${FRONTEND_LOG}" 2>&1 < /dev/null &
  echo $! > "${FRONTEND_PID_FILE}"
  echo "[INFO] Frontend PID: $(cat "${FRONTEND_PID_FILE}")"
}

cleanup() {
  echo ""
  echo "[INFO] Shutting down..."
  if [[ -f "${BACKEND_PID_FILE}" ]]; then
    kill "$(cat "${BACKEND_PID_FILE}")" >/dev/null 2>&1 || true
  fi
  if [[ -f "${FRONTEND_PID_FILE}" ]]; then
    kill "$(cat "${FRONTEND_PID_FILE}")" >/dev/null 2>&1 || true
  fi
}

trap cleanup INT TERM

printf '[INFO] Root: %s\n' "${ROOT_DIR}"
printf '[INFO] Backend: %s\n' "${BACKEND_DIR}"
printf '[INFO] Frontend: %s\n' "${FRONTEND_DIR}"
printf '[INFO] Logs: %s\n' "${LOG_DIR}"

start_backend
start_frontend

echo ""
echo "[DONE] Guardian startup launched."
echo "       Backend:  http://localhost:8881"
echo "       Frontend: http://localhost:5173"
echo ""
echo "[INFO] Logs:"
echo "       Backend  -> ${BACKEND_LOG}"
echo "       Frontend -> ${FRONTEND_LOG}"
echo ""
echo "[INFO] This script is detached via nohup; stop processes with PIDs from logs/*.pid or use kill."

exit 0
