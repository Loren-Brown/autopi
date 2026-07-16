#!/bin/bash
set -euo pipefail

if dpkg -s i2c-tools &>/dev/null; then
  echo "i2c-tools already installed, skipping apt install."
else
  echo "Installing Real Time Clock Tools..."
  sudo apt-get install i2c-tools -y
fi

echo "Enable i2C in raspberry pi config"
sudo raspi-config nonint do_i2c 0
echo "Manually Restarting i2c service"
sudo modprobe i2c-dev

echo ""
echo "Validating RTC on I2C bus 1..."
I2C_OUT="$(sudo i2cdetect -y 1)"
echo "${I2C_OUT}"

# Address 0x68 is column 8 on the "60:" row (awk field 10: "60:" + 8 cells).
CELL="$(awk '/^60:/ { print $10 }' <<< "${I2C_OUT}")"
if [[ "${CELL}" == "68" || "${CELL}" == "UU" ]]; then
  echo "RTC OK: found ${CELL} at address 0x68"
else
  echo "RTC validation failed: expected 68 or UU at address 0x68, got '${CELL:-missing}'" >&2
  exit 1
fi
