#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="/boot/firmware/config.txt"
ADDED=0

# True only for an active (non-commented) config line.
has_active_line() {
  local needle="$1"
  grep -qE "^[[:space:]]*${needle}" "${CONFIG_FILE}"
}

ensure_line() {
  local line="$1"
  local label="$2"
  if has_active_line "${line}"; then
    echo "${label} already present (active) in ${CONFIG_FILE}."
    return 0
  fi
  echo "Adding ${label} to ${CONFIG_FILE}..."
  {
    echo ""
    echo "# PiCAN3"
    echo "${line}"
  } | sudo tee -a "${CONFIG_FILE}" > /dev/null
  ADDED=1
}

ensure_line 'dtparam=spi=on' 'dtparam=spi=on'
ensure_line 'dtoverlay=mcp2515-can0,oscillator=16000000,interrupt=25' \
  'dtoverlay=mcp2515-can0'
ensure_line 'dtoverlay=spi-bcm2835-overlay' 'dtoverlay=spi-bcm2835-overlay'

if [[ "${ADDED}" -eq 1 ]]; then
  echo "PiCAN3 overlay config updated. Rebooting..."
  sudo reboot
fi

echo "PiCAN3 overlays already configured; no reboot needed."
