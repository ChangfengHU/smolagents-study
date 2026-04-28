#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${GROK_WECHAT_HOST:-127.0.0.1}"
PORT="${GROK_WECHAT_PORT:-8765}"
LOG_FILE="${ROOT_DIR}/.grok_wechat_server.log"
PID_FILE="${ROOT_DIR}/.grok_wechat_server.pid"

echo "[restart] root: ${ROOT_DIR}"
echo "[restart] python: ${PYTHON_BIN}"
echo "[restart] host: ${HOST} port: ${PORT}"

# Stop previous process by pid file if present.
if [[ -f "${PID_FILE}" ]]; then
  OLD_PID="$(cat "${PID_FILE}" || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
    echo "[restart] stopping previous pid: ${OLD_PID}"
    kill "${OLD_PID}" || true
    sleep 1
    if kill -0 "${OLD_PID}" 2>/dev/null; then
      echo "[restart] force killing pid: ${OLD_PID}"
      kill -9 "${OLD_PID}" || true
    fi
  fi
fi

# Also clean up any stale process matching the script path.
pkill -f "examples/grok_wechat_server.py" 2>/dev/null || true

echo "[restart] starting server..."
cd "${ROOT_DIR}"
nohup env GROK_WECHAT_HOST="${HOST}" GROK_WECHAT_PORT="${PORT}" \
  "${PYTHON_BIN}" "examples/grok_wechat_server.py" > "${LOG_FILE}" 2>&1 &
NEW_PID=$!
echo "${NEW_PID}" > "${PID_FILE}"

sleep 1
if kill -0 "${NEW_PID}" 2>/dev/null; then
  echo "[restart] started. pid=${NEW_PID}"
  echo "[restart] log: ${LOG_FILE}"
  echo "[restart] url: http://${HOST}:${PORT}"
else
  echo "[restart] failed to start. showing log tail:"
  tail -n 50 "${LOG_FILE}" || true
  exit 1
fi
