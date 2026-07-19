#!/usr/bin/env bash
# Generate the full channels catalog from the RomRaider logger XML.
# Requires ROMRAIDER_XML in the laptop .env (see .env.example).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
GENERATOR="${SCRIPT_DIR}/src/ssm-collector/generate_channels_json.py"
CHANNELS_JSON="${SCRIPT_DIR}/src/ssm-collector/configs/channels.json"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: .env not found at ${ENV_FILE}" >&2
  echo "Copy the example and set ROMRAIDER_XML:" >&2
  echo "  cp .env.example .env" >&2
  echo "  # then edit .env and set ROMRAIDER_XML=docs/romraider/.../logger_*.xml" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${ENV_FILE}"

if [[ -z "${ROMRAIDER_XML:-}" ]]; then
  echo "Error: ROMRAIDER_XML is not set in .env" >&2
  echo "Add a line like:" >&2
  echo "  ROMRAIDER_XML=docs/romraider/logger_v370/logger_STD_EN_v370.xml" >&2
  echo "(see .env.example)." >&2
  exit 1
fi

if [[ "${ROMRAIDER_XML}" = /* ]]; then
  LOCAL_XML="${ROMRAIDER_XML}"
else
  LOCAL_XML="${SCRIPT_DIR}/${ROMRAIDER_XML}"
fi

if [[ ! -f "${LOCAL_XML}" ]]; then
  echo "Error: RomRaider XML not found: ${LOCAL_XML}" >&2
  echo "Fix ROMRAIDER_XML in .env so it points at an existing logger_*.xml" >&2
  echo "(usually under docs/romraider/ — gitignored; download / copy the file there)." >&2
  exit 1
fi

echo "Using RomRaider XML: ${LOCAL_XML}"

if [[ ! -f "${CHANNELS_JSON}" ]]; then
  mkdir -p "$(dirname "${CHANNELS_JSON}")"
  printf '%s\n' '{' '  "channels": []' '}' > "${CHANNELS_JSON}"
  echo "Created empty poll list: ${CHANNELS_JSON}"
fi

cd "${SCRIPT_DIR}"
uv run "${GENERATOR}"
