#!/usr/bin/env bash
# Install systemd units so SSM collector + web UI start on boot.
set -euo pipefail

USER_NAME="$(id -un)"
HOME_DIR="$(getent passwd "${USER_NAME}" | cut -d: -f6)"
APP_DIR="${HOME_DIR}/autopi"
UV_BIN="${HOME_DIR}/.local/bin/uv"
AP_ENV="/etc/autopi/ap.env"

GUEST_GATEWAY="10.3.141.1"
if [[ -f "${AP_ENV}" ]]; then
  if [[ -r "${AP_ENV}" ]]; then
    # shellcheck source=/dev/null
    source "${AP_ENV}"
  else
    # shellcheck source=/dev/null
    source <(sudo cat "${AP_ENV}")
  fi
fi
COLLECTOR_WS_URL="${COLLECTOR_WS_URL:-ws://${GUEST_GATEWAY}:8090/ws}"

if [[ ! -x "${UV_BIN}" ]]; then
  echo "Error: uv not found at ${UV_BIN}. Run install_uv.sh first." >&2
  exit 1
fi

if [[ ! -d "${APP_DIR}/src" ]]; then
  echo "Warning: ${APP_DIR}/src not found yet. Deploy the app before relying on these services."
fi

sudo tee /etc/systemd/system/autopi-collector.service > /dev/null <<EOF
[Unit]
Description=autopi SSM telemetry collector
After=network-online.target sys-subsystem-net-devices-can0.device
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${APP_DIR}
Environment=CAN_MODE=native
Environment=COLLECTOR_HOST=0.0.0.0
Environment=COLLECTOR_PORT=8090
Environment=SSM_ECU_ID=5C42504007
ExecStart=${UV_BIN} run --directory ${APP_DIR} src/main.py --collector
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/autopi-web.service > /dev/null <<EOF
[Unit]
Description=autopi SSM dashboard UI
After=autopi-collector.service network-online.target
Wants=autopi-collector.service

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${APP_DIR}
Environment=WEB_HOST=0.0.0.0
Environment=WEB_PORT=8080
Environment=COLLECTOR_WS_URL=${COLLECTOR_WS_URL}
ExecStart=${UV_BIN} run --directory ${APP_DIR} src/main.py --web
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable autopi-collector.service autopi-web.service

if [[ -d "${APP_DIR}/src" ]]; then
  sudo systemctl restart autopi-collector.service
  sudo systemctl restart autopi-web.service
  echo "autopi collector + web services enabled and started."
else
  echo "autopi collector + web services enabled (start after ./deploy.sh)."
fi

echo "  collector: systemctl status autopi-collector"
echo "  web:       systemctl status autopi-web"
echo "  dashboard: http://${GUEST_GATEWAY}:8080/"
