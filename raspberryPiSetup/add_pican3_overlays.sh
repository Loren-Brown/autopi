#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="/boot/firmware/config.txt"

if grep -q "mcp2515-can0" "${CONFIG_FILE}"; then
  echo "PiCAN3 overlays already present in ${CONFIG_FILE}, skipping."
  exit 0
fi

echo "" | sudo tee -a "${CONFIG_FILE}" > /dev/null
echo "# PiCAN3" | sudo tee -a "${CONFIG_FILE}" > /dev/null
echo "dtparam=spi=on" | sudo tee -a "${CONFIG_FILE}" > /dev/null
echo "dtoverlay=mcp2515-can0,oscillator=16000000,interrupt=25" | sudo tee -a "${CONFIG_FILE}" > /dev/null
echo "dtoverlay=spi-bcm2835-overlay" | sudo tee -a "${CONFIG_FILE}" > /dev/null

echo "PiCAN3 overlays added to ${CONFIG_FILE}. Rebooting..."
sudo reboot