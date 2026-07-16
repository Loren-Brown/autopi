#!/usr/bin/env bash
# Fast-sync only the web UI to the Pi — no uv sync, no service restart.
# After this, a normal browser refresh (Cmd+R) loads the new HTML/CSS/JS/config.
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

REMOTE="${PI_USER}@${PI_HOST}"
REMOTE_DIR="/home/${PI_USER}/autopi"
SRC="${SCRIPT_DIR}/src/autopi-app/"
DEST="${REMOTE}:${REMOTE_DIR}/src/autopi-app/"

echo "Syncing UI → ${DEST}"
rsync -av --delete \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  "${SRC}" "${DEST}"

echo
echo "Done. Soft-refresh the browser (Cmd+R / Ctrl+R) — no restart needed for HTML/CSS/JS/config."
echo "  Dash:     http://${PI_HOST}:8080/dashboard"
echo "  Detailed: http://${PI_HOST}:8080/detailed"
echo
echo "Python changes in web_main.py still need a web process restart."
