#!/usr/bin/env bash
# Start BlockFlow in the background on a RunPod pod, with its data on the volume.
#
# Usage (on the pod, from the cloned repo):
#   ./start-blockflow.sh          # start, or restart if already running
#   ./start-blockflow.sh stop     # stop it
#
# Optional environment:
#   BLOCKFLOW_DATA_DIR  Settings, credentials, run history, flows, outputs
#                       (default: /workspace/.blockflow). When it is not set, the
#                       new folder does not exist yet and the old default
#                       /workspace/blockflow-data does, that folder is moved here
#                       once and a symlink is left at the old path.
#   PYTHON_LIBS         Persistent Python folder whose bin/ holds uv
#                       (default: /workspace/.python; its bin/ is put first on PATH)
#   FRONTEND_PORT       Web UI port to expose via RunPod (default: 9000)
#   FRONTEND_HOST       Web UI bind address (default: 0.0.0.0)
#   BACKEND_PORT        FastAPI port, stays on localhost (default: 9001)
#   BLOCKFLOW_WAIT      Seconds to wait for the UI to answer (default: 600; the first
#                       start installs Python and npm dependencies)
#   BLOCKFLOW_LOG       Log file (default: $BLOCKFLOW_DATA_DIR/blockflow.log)
#   BLOCKFLOW_USE_LOCAL_PRESETS
#                       1: presets in local_presets/ replace registry presets with
#                       the same id; only: local presets only; empty: registry only
#                       (default: 1)
#   BLOCKFLOW_LOCAL_PRESETS_DIR
#                       Folder for local presets (default: <repo>/local_presets)
#   UV_CACHE_DIR, UV_PYTHON_INSTALL_DIR
#                       uv download cache / downloaded Pythons, kept on the volume
#                       (default: /workspace/.uv-cache, /workspace/.uv-python)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEFAULT_DATA_DIR="/workspace/.blockflow"
LEGACY_DATA_DIR="/workspace/blockflow-data"   # default before; migrated once
MIGRATE_FROM=""
if [ -z "${BLOCKFLOW_DATA_DIR:-}" ] && [ ! -e "$DEFAULT_DATA_DIR" ] \
   && [ -d "$LEGACY_DATA_DIR" ] && [ ! -L "$LEGACY_DATA_DIR" ]; then
  MIGRATE_FROM="$LEGACY_DATA_DIR"
fi
export BLOCKFLOW_DATA_DIR="${BLOCKFLOW_DATA_DIR:-$DEFAULT_DATA_DIR}"
PYTHON_LIBS="${PYTHON_LIBS:-/workspace/.python}"
case ":$PATH:" in
  *":${PYTHON_LIBS}/bin:"*) ;;
  *) export PATH="${PYTHON_LIBS}/bin:$PATH" ;;
esac
export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/.uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/workspace/.uv-python}"
export FRONTEND_PORT="${FRONTEND_PORT:-9000}"
export FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
export BACKEND_PORT="${BACKEND_PORT:-9001}"
export BLOCKFLOW_NO_OPEN=1   # headless pod: do not try to open a browser
export BLOCKFLOW_USE_LOCAL_PRESETS="${BLOCKFLOW_USE_LOCAL_PRESETS-1}"   # local preset fixes on by default
BLOCKFLOW_WAIT="${BLOCKFLOW_WAIT:-600}"

# Until the data is migrated, a running BlockFlow's PID file is still in the
# old folder; stop that instance before moving the folder.
PID_FILE="${MIGRATE_FROM:-$BLOCKFLOW_DATA_DIR}/blockflow.pid"

migrate_data_dir() {
  [ -n "$MIGRATE_FROM" ] || return 0
  echo "==> Moving BlockFlow data ${MIGRATE_FROM} -> ${BLOCKFLOW_DATA_DIR}"
  mv "$MIGRATE_FROM" "$BLOCKFLOW_DATA_DIR"
  # Absolute paths stored under the old folder (e.g. job records) keep working.
  ln -s "$BLOCKFLOW_DATA_DIR" "$MIGRATE_FROM"
  MIGRATE_FROM=""
  PID_FILE="${BLOCKFLOW_DATA_DIR}/blockflow.pid"
}

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

# `ss`/`lsof` are often missing on pod images, so read /proc directly.
# Prints "pid<TAB>pgid<TAB>cwd<TAB>cmdline" for each process listening on TCP port $1.
port_owners() {
  python3 - "$1" <<'PY'
import glob, os, sys
port = int(sys.argv[1])
inodes = set()
for table in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        lines = open(table).read().splitlines()[1:]
    except OSError:
        continue
    for line in lines:
        f = line.split()
        if len(f) > 9 and f[3] == "0A" and int(f[1].rsplit(":", 1)[1], 16) == port:
            inodes.add(f[9])
for fd in glob.glob("/proc/[0-9]*/fd/*"):
    try:
        link = os.readlink(fd)
    except OSError:
        continue
    if link.startswith("socket:[") and link[8:-1] in inodes:
        pid = fd.split("/")[2]
        inodes.discard(link[8:-1])
        try:
            stat = open(f"/proc/{pid}/stat").read()
            pgid = stat.rsplit(")", 1)[1].split()[2]
            cwd = os.readlink(f"/proc/{pid}/cwd")
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
        except (OSError, IndexError):
            pgid, cwd, cmd = "?", "?", "?"
        print(f"{pid}\t{pgid}\t{cwd}\t{cmd}")
PY
}

# Free FRONTEND_PORT / BACKEND_PORT. Leftover BlockFlow processes (started by
# hand or by an older script, so not in the PID file) are recognised by their
# working directory inside this repo and stopped with their process group;
# any other program is left alone and we refuse to start.
free_ports() {
  local port opid opgid ocwd ocmd
  for port in "$FRONTEND_PORT" "$BACKEND_PORT"; do
    while IFS=$'\t' read -r opid opgid ocwd ocmd; do
      [ -n "$opid" ] || continue
      if [[ "$ocwd" == "$REPO_DIR"* ]]; then
        echo "==> Stopping a BlockFlow process not started by this script (port ${port}, pid ${opid}: ${ocmd})"
        if [[ "$opgid" =~ ^[0-9]+$ ]] && [ "$opgid" != "$(ps -o pgid= $$ | tr -d ' ')" ]; then
          kill -TERM -- "-$opgid" 2>/dev/null || true
        fi
        kill -TERM "$opid" 2>/dev/null || true
      else
        echo "ERROR: port ${port} is used by another program (pid ${opid}: ${ocmd})." >&2
        echo "       Stop it or choose other ports with FRONTEND_PORT=... / BACKEND_PORT=..." >&2
        exit 1
      fi
    done < <(port_owners "$port")
  done
  for _ in $(seq 1 15); do
    [ -z "$(port_owners "$FRONTEND_PORT")$(port_owners "$BACKEND_PORT")" ] && return 0
    sleep 1
  done
  for port in "$FRONTEND_PORT" "$BACKEND_PORT"; do
    port_owners "$port" | cut -f1 | xargs -r kill -9 2>/dev/null || true
  done
  sleep 1
  if [ -n "$(port_owners "$FRONTEND_PORT")$(port_owners "$BACKEND_PORT")" ]; then
    echo "ERROR: ports ${FRONTEND_PORT}/${BACKEND_PORT} are still in use." >&2
    exit 1
  fi
}

if [ "${1:-}" = "stop" ]; then
  stop_running
  free_ports
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
free_ports
migrate_data_dir
mkdir -p "$BLOCKFLOW_DATA_DIR"
LOG_FILE="${BLOCKFLOW_LOG:-${BLOCKFLOW_DATA_DIR}/blockflow.log}"

echo "==> Data: ${BLOCKFLOW_DATA_DIR}"
echo "==> uv: $(command -v uv)"
echo "==> Starting BlockFlow (log: ${LOG_FILE})"
cd "$REPO_DIR"
setsid nohup uv run app.py >>"$LOG_FILE" 2>&1 < /dev/null &
echo $! >"$PID_FILE"
pid="$(cat "$PID_FILE")"

echo -n "==> Waiting for the web UI on port ${FRONTEND_PORT}"
deadline=$((SECONDS + BLOCKFLOW_WAIT))
# Ready only when the UI answers AND the port belongs to the BlockFlow we just
# started (its process group), not to something else.
ui_is_ours() {
  [ "$(port_owners "$FRONTEND_PORT" | cut -f2 | head -1)" = "$pid" ] \
    && curl -fsS -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}" 2>/dev/null
}
until ui_is_ours; do
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
