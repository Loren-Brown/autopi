#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: .env file not found." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${ENV_FILE}"

: "${PI_HOST:?PI_HOST must be set in .env}"
: "${PI_USER:?PI_USER must be set in .env}"
: "${SOCKETCAND_PORT:=29536}"
: "${SOCKETCAND_HOST:=localhost}"
: "${COLLECTOR_WS_URL:=ws://127.0.0.1:8090/ws}"

# Pass all arguments through to the Python entry point.
# Default: SSM logger.  --web starts collector + UI together on the laptop.
ENTRY="src/main.py"
PASS_ARGS=("$@")

REMOTE="${PI_USER}@${PI_HOST}"

has_flag() {
  local needle="$1"
  local arg
  for arg in "${PASS_ARGS[@]+"${PASS_ARGS[@]}"}"; do
    if [[ "${arg}" == "${needle}" ]]; then
      return 0
    fi
  done
  return 1
}

echo "Deploying to Pi..."
"${SCRIPT_DIR}/deploy.sh"

echo "Ensuring can0 is up on Pi..."
ssh "${REMOTE}" "ip link show can0 | grep -q 'state UP' || sudo ip link set can0 up type can bitrate 500000"
echo "  can0: up"

echo "Checking socketcand on Pi (${PI_HOST})..."
if ! ssh -o ConnectTimeout=5 "${REMOTE}" "systemctl is-active --quiet socketcand" 2>/dev/null; then
  echo "  socketcand not running — starting it..."
  ssh "${REMOTE}" "sudo systemctl start socketcand"
fi
echo "  socketcand: running"

echo "Checking SSH tunnel (localhost:${SOCKETCAND_PORT})..."
if ! lsof -i "TCP:${SOCKETCAND_PORT}" -sTCP:LISTEN -n -P 2>/dev/null | grep -q ssh; then
  echo "  Tunnel not open — opening it..."
  ssh -L "${SOCKETCAND_PORT}:localhost:${SOCKETCAND_PORT}" "${REMOTE}" -N -f
fi
echo "  SSH tunnel: open"

echo ""
if has_flag --web; then
  echo "Starting SSM collector + web UI on laptop..."
  echo "  collector → ${COLLECTOR_WS_URL}"
  echo "  dashboard → http://localhost:8080/"

  uv run "${SCRIPT_DIR}/${ENTRY}" --collector &
  COLLECTOR_PID=$!

  cleanup() {
    kill "${COLLECTOR_PID}" 2>/dev/null || true
    wait "${COLLECTOR_PID}" 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM

  sleep 1
  COLLECTOR_WS_URL="${COLLECTOR_WS_URL}" uv run "${SCRIPT_DIR}/${ENTRY}" --web
else
  uv run "${SCRIPT_DIR}/${ENTRY}" ${PASS_ARGS[@]+"${PASS_ARGS[@]}"}
fi
