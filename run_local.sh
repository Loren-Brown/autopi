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

# Pass all arguments through to the Python entry point.
# Default: SSM logger.  --web starts collector + UI together on the Pi.
PASS_ARGS=("$@")

REMOTE="${PI_USER}@${PI_HOST}"
REMOTE_DIR="/home/${PI_USER}/autopi"

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

echo "Stopping socketcand on Pi (${PI_HOST})..."
if ssh -o ConnectTimeout=5 "${REMOTE}" "systemctl is-active --quiet socketcand" 2>/dev/null; then
  ssh "${REMOTE}" "sudo systemctl stop socketcand"
  echo "  socketcand: stopped"
else
  echo "  socketcand: already stopped"
fi

RESTORE_WEB_SERVICES=0
if has_flag --web || has_flag --collector; then
  echo "Stopping systemd autopi web/collector (free :8080 / :8090)..."
  if ssh -o ConnectTimeout=5 "${REMOTE}" \
      "systemctl is-active --quiet autopi-web || systemctl is-active --quiet autopi-collector" 2>/dev/null; then
    ssh "${REMOTE}" "sudo systemctl stop autopi-web.service autopi-collector.service"
    RESTORE_WEB_SERVICES=1
    echo "  autopi-web + autopi-collector: stopped"
  else
    echo "  autopi-web + autopi-collector: already stopped"
  fi
fi

restore_web_services() {
  if [[ "${RESTORE_WEB_SERVICES}" -eq 1 ]]; then
    echo ""
    echo "Restarting systemd autopi web/collector on Pi..."
    ssh -o ConnectTimeout=5 "${REMOTE}" \
      "sudo systemctl start autopi-collector.service autopi-web.service" 2>/dev/null \
      && echo "  services: restarted" \
      || echo "  services: restart skipped (Pi unreachable or units missing)"
  fi
}
trap restore_web_services EXIT

echo "Closing SSH tunnel (localhost:${SOCKETCAND_PORT})..."
TUNNEL_PID=$(lsof -i "TCP:${SOCKETCAND_PORT}" -sTCP:LISTEN -n -P 2>/dev/null | awk '/ssh/ {print $2}' | head -1 || true)
if [[ -n "${TUNNEL_PID}" ]]; then
  kill "${TUNNEL_PID}"
  echo "  SSH tunnel: closed (pid ${TUNNEL_PID})"
else
  echo "  SSH tunnel: already closed"
fi

echo "Ensuring can0 is up on Pi..."
ssh "${REMOTE}" "ip link show can0 | grep -q 'state UP' || sudo ip link set can0 up type can bitrate 500000"
echo "  can0: up"

echo ""
if has_flag --web; then
  echo "Starting SSM collector + web UI on Pi..."
  echo "  collector → ws://${PI_HOST}:8090/ws"
  echo "  dashboard → http://${PI_HOST}:8080/"
  # Use --directory so backgrounded uv still finds src/main.py.
  ssh -t "${REMOTE}" "\
    UV_BIN=\"\${HOME}/.local/bin/uv\"; \
    \"\${UV_BIN}\" run --directory \"${REMOTE_DIR}\" src/main.py --collector & \
    COLLECTOR_PID=\$!; \
    trap 'kill \"\${COLLECTOR_PID}\" 2>/dev/null; wait \"\${COLLECTOR_PID}\" 2>/dev/null' EXIT INT TERM; \
    sleep 1; \
    COLLECTOR_WS_URL=ws://${PI_HOST}:8090/ws \"\${UV_BIN}\" run --directory \"${REMOTE_DIR}\" src/main.py --web"
else
  ssh -t "${REMOTE}" "\
    \"\${HOME}/.local/bin/uv\" run --directory \"${REMOTE_DIR}\" src/main.py ${PASS_ARGS[*]+"${PASS_ARGS[*]}"}"
fi
