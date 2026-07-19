#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
PI_CONFIGS_DIR="src/ssm-collector/configs"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: .env file not found. Copy .env.example to .env and set PI_HOST and PI_USER." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${ENV_FILE}"

: "${PI_HOST:?PI_HOST must be set in .env}"
: "${PI_USER:?PI_USER must be set in .env}"
: "${ROMRAIDER_XML:?ROMRAIDER_XML must be set in .env (path to your RomRaider logger XML)}"

REMOTE="${PI_USER}@${PI_HOST}"
REMOTE_DIR="/home/${PI_USER}/autopi"

# Resolve laptop source XML (repo-relative or absolute).
if [[ "${ROMRAIDER_XML}" = /* ]]; then
  LOCAL_XML="${ROMRAIDER_XML}"
else
  LOCAL_XML="${SCRIPT_DIR}/${ROMRAIDER_XML}"
fi
if [[ ! -f "${LOCAL_XML}" ]]; then
  echo "Error: ROMRAIDER_XML not found: ${LOCAL_XML}" >&2
  echo "Set ROMRAIDER_XML in .env to your logger XML (e.g. docs/romraider/…)." >&2
  exit 1
fi

XML_BASENAME="$(basename "${LOCAL_XML}")"
PI_XML_PATH="${PI_CONFIGS_DIR}/${XML_BASENAME}"

echo "Syncing to ${REMOTE}:${REMOTE_DIR}..."

# Exclude Pi-only logger XML so --delete does not wipe the copy we place next.
rsync -av --delete \
  --exclude='.env' \
  --exclude='.venv' \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='docs/' \
  --exclude='src/ssm-collector/configs/*.xml' \
  "${SCRIPT_DIR}/" "${REMOTE}:${REMOTE_DIR}/"

echo "Copying RomRaider XML to Pi as ${PI_XML_PATH}..."
ssh "${REMOTE}" "mkdir -p ${REMOTE_DIR}/${PI_CONFIGS_DIR} && rm -f ${REMOTE_DIR}/${PI_CONFIGS_DIR}/*.xml"
rsync -av "${LOCAL_XML}" "${REMOTE}:${REMOTE_DIR}/${PI_XML_PATH}"

echo "Making setup scripts executable..."
ssh "${REMOTE}" "chmod +x ${REMOTE_DIR}/raspberryPiSetup/*.sh"

echo "Writing .env for Pi (CAN_MODE=native)..."
# No ROMRAIDER_XML on the Pi — runtime finds the single *.xml under configs/.
# shellcheck disable=SC2153
ssh "${REMOTE}" "cat > ${REMOTE_DIR}/.env" <<EOF
CAN_MODE=native
SSM_ECU_ID=${SSM_ECU_ID:-5C42504007}
EOF

echo "Installing dependencies on Pi..."
ssh "${REMOTE}" "bash -lc 'cd ${REMOTE_DIR} && uv sync --no-dev'"

echo "Done. To run: ssh ${REMOTE} 'cd ${REMOTE_DIR} && uv run src/main.py'"
