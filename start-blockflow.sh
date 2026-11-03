#!/usr/bin/env bash
# Start BlockFlow in the background on a RunPod pod, with its data on the volume.
#
# Usage (on the pod, from the cloned repo):
#   ./start-blockflow.sh          # start, or restart if already running
#   ./start-blockflow.sh stop     # stop it
#
# Optional environment:
#   BLOCKFLOW_DATA_DIR  Settings, credentials, run history, flows, outputs
#                       (default: /workspace/blockflow-data)
#   PYTHON_LIBS         Persistent Python folder whose bin/ holds uv
#                       (default: /workspace/.python; its bin/ is put first on PATH)
#   FRONTEND_PORT       Web UI port to expose via RunPod (default: 3200)
#   FRONTEND_HOST       Web UI bind address, if app.py supports it (default: 0.0.0.0)
#   BACKEND_PORT        FastAPI port, stays on localhost (default: 8000)
#   BLOCKFLOW_WAIT      Seconds to wait for the UI to answer (default: 600; the first
#                       start installs Python and npm dependencies)
#   BLOCKFLOW_LOG       Log file (default: $BLOCKFLOW_DATA_DIR/blockflow.log)
#   UV_CACHE_DIR, UV_PYTHON_INSTALL_DIR
#                       uv download cache / downloaded Pythons, kept on the volume
#                       (default: /workspace/.uv-cache, /workspace/.uv-python)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export BLOCKFLOW_DATA_DIR="${BLOCKFLOW_DATA_DIR:-/workspace/blockflow-data}"
PYTHON_LIBS="${PYTHON_LIBS:-/workspace/.python}"
case ":$PATH:" in
  *":${PYTHON_LIBS}/bin:"*) ;;
  *) export PATH="${PYTHON_LIBS}/bin:$PATH" ;;
esac
export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/.uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/workspace/.uv-python}"
export FRONTEND_PORT="${FRONTEND_PORT:-3200}"
export FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
export BACKEND_PORT="${BACKEND_PORT:-8000}"
export BLOCKFLOW_NO_OPEN=1   # headless pod: do not try to open a browser
BLOCKFLOW_WAIT="${BLOCKFLOW_WAIT:-600}"

mkdir -p "$BLOCKFLOW_DATA_DIR"
LOG_FILE="${BLOCKFLOW_LOG:-${BLOCKFLOW_DATA_DIR}/blockflow.log}"
PID_FILE="${BLOCKFLOW_DATA_DIR}/blockflow.pid"

# app.py starts uvicorn and Next.js as children. BlockFlow runs in its own
# process group (setsid), so stopping it signals the whole group and no child
# is left holding the ports.
stop_running() {
  [ -f "$PID_FILE" ] || return 0
  local pid
  pid="$(cat "$PID_FILE")"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "==> Stopping BlockFlow (pid $pid)"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 15); do
      kill -0 -- "-$pid" 2>/dev/null || break
      sleep 1
    done
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
}

if [ "${1:-}" = "stop" ]; then
  stop_running
  exit 0
fi
if [ -n "${1:-}" ]; then
  echo "Usage: $0 [stop]" >&2
  exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not found (looked in ${PYTHON_LIBS}/bin and PATH). Install it with: pip install uv" >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm not found. BlockFlow's web UI needs Node.js." >&2
  exit 1
fi

stop_running

echo "==> Data: ${BLOCKFLOW_DATA_DIR}"
echo "==> uv: $(command -v uv)"
echo "==> Starting BlockFlow (log: ${LOG_FILE})"
cd "$REPO_DIR"
setsid nohup uv run app.py >>"$LOG_FILE" 2>&1 < /dev/null &
echo $! >"$PID_FILE"
pid="$(cat "$PID_FILE")"

echo -n "==> Waiting for the web UI on port ${FRONTEND_PORT}"
deadline=$((SECONDS + BLOCKFLOW_WAIT))
until curl -fsS -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}" 2>/dev/null; do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo
    echo "ERROR: BlockFlow exited during startup. Last log lines:" >&2
    tail -n 30 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    exit 1
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo
    echo "ERROR: the web UI did not answer within ${BLOCKFLOW_WAIT}s (still running as pid ${pid})." >&2
    echo "       Check the log: ${LOG_FILE}" >&2
    exit 1
  fi
  echo -n "."
  sleep 2
done
echo " ready"
echo "==> BlockFlow running (pid ${pid}): http://127.0.0.1:${FRONTEND_PORT}"
[ -n "${RUNPOD_POD_ID:-}" ] && echo "    Public URL: https://${RUNPOD_POD_ID}-${FRONTEND_PORT}.proxy.runpod.net"
exit 0
