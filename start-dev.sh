#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"
LOG_DIR="${ROOT_DIR}/logs"
BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"

mkdir -p "${LOG_DIR}"

echo "[CHECK] file line limit rule"
if ! bash "${ROOT_DIR}/.specify/scripts/bash/check-file-line-limit.sh" --mode changed; then
  echo "[FAIL] line-limit check failed. please split over-limit files first."
  exit 1
fi

start_backend() {
  nohup bash -lc "cd \"${BACKEND_DIR}\" && python -m uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8881" >>"${BACKEND_LOG}" 2>&1 &
}

start_frontend() {
  nohup bash -lc "cd \"${FRONTEND_DIR}\" && npm run dev" >>"${FRONTEND_LOG}" 2>&1 &
}

start_backend
start_frontend

echo "[DONE] backend and frontend started with nohup."
echo "       Backend:  http://localhost:8881"
echo "       Frontend: http://localhost:5173"
echo "       Logs:"
echo "         backend  -> ${BACKEND_LOG}"
echo "         frontend -> ${FRONTEND_LOG}"
