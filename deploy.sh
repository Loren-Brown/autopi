#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: .env file not found. Copy .env.example to .env and set PI_HOST and PI_USER." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${ENV_FILE}"

: "${PI_HOST:?PI_HOST must be set in .env}"
: "${PI_USER:?PI_USER must be set in .env}"

REMOTE="${PI_USER}@${PI_HOST}"
REMOTE_DIR="/home/${PI_USER}/autopi"

echo "Syncing to ${REMOTE}:${REMOTE_DIR}..."

rsync -av --delete \
  --exclude='.env' \
  --exclude='.venv' \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='docs/' \
  "${SCRIPT_DIR}/" "${REMOTE}:${REMOTE_DIR}/"

echo "Making setup scripts executable..."
ssh "${REMOTE}" "chmod +x ${REMOTE_DIR}/raspberryPiSetup/*.sh"

echo "Writing .env for Pi (CAN_MODE=native)..."
ssh "${REMOTE}" "cat > ${REMOTE_DIR}/.env" <<EOF
CAN_MODE=native
EOF

echo "Installing dependencies on Pi..."
ssh "${REMOTE}" "bash -lc 'cd ${REMOTE_DIR} && uv sync --no-dev'"

echo "Done. To run: ssh ${REMOTE} 'cd ${REMOTE_DIR} && uv run src/main.py'"
