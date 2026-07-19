#!/usr/bin/env bash
# Kill anything bound to the SSM collector port (default 8090) on this machine
# and on the Pi (PI_HOST / PI_USER from .env).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
PORT="${COLLECTOR_PORT:-8090}"

kill_port_local() {
  local port="$1"
  echo "Dev machine: freeing :${port}..."
  local pids
  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    echo "  nothing listening on :${port}"
    return 0
  fi
  # shellcheck disable=SC2086
  echo "  killing PIDs: ${pids}"
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true
  sleep 0.3
  # shellcheck disable=SC2086
  kill -9 ${pids} 2>/dev/null || true
  if lsof -tiTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  warning: :${port} still in use" >&2
  else
    echo "  :${port} free"
  fi
}

kill_port_pi() {
  local port="$1"
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo "Pi: skip (.env not found)" >&2
    return 0
  fi
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  if [[ -z "${PI_HOST:-}" || -z "${PI_USER:-}" ]]; then
    echo "Pi: skip (PI_HOST / PI_USER not set in .env)" >&2
    return 0
  fi

  local remote="${PI_USER}@${PI_HOST}"
  echo "Pi (${remote}): freeing :${port}..."
  ssh -o ConnectTimeout=10 "${remote}" bash -s -- "${port}" <<'EOF'
set -euo pipefail
PORT="$1"

sudo systemctl stop autopi-collector.service 2>/dev/null || true

if command -v fuser >/dev/null 2>&1; then
  sudo fuser -k "${PORT}/tcp" 2>/dev/null || true
fi

PIDS="$(ss -lptn "sport = :${PORT}" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u || true)"
if [[ -n "${PIDS}" ]]; then
  echo "  killing PIDs: ${PIDS}"
  # shellcheck disable=SC2086
  sudo kill ${PIDS} 2>/dev/null || true
  sleep 0.3
  # shellcheck disable=SC2086
  sudo kill -9 ${PIDS} 2>/dev/null || true
fi

pkill -f "src/main.py --collector" 2>/dev/null || true

if ss -lptn "sport = :${PORT}" 2>/dev/null | grep -q ":${PORT}"; then
  echo "  warning: :${PORT} still in use" >&2
  ss -lptn "sport = :${PORT}" >&2 || true
else
  echo "  :${PORT} free"
fi
EOF
}

kill_port_local "${PORT}"
kill_port_pi "${PORT}"
echo "Done."
