#!/bin/bash
set -euo pipefail

CONFIG_FILE="/boot/firmware/config.txt"
ADDED=0

# True only for an active (non-commented) config line.
has_active_line() {
  local needle="$1"
  # Line may start with whitespace, but must not start with '#'.
  grep -qE "^[[:space:]]*${needle}([[:space:]]|#|$)" "${CONFIG_FILE}"
}

if has_active_line 'dtparam=i2c_arm=on'; then
  echo "dtparam=i2c_arm=on already present (active) in ${CONFIG_FILE}."
else
  echo "Adding dtparam=i2c_arm=on to ${CONFIG_FILE}..."
  {
    echo ""
    echo "# PiCAN 3 Real Time Clock — enable I2C"
    echo "dtparam=i2c_arm=on"
  } | sudo tee -a "${CONFIG_FILE}" > /dev/null
  ADDED=1
fi

if has_active_line 'dtoverlay=i2c-rtc,pcf8523'; then
  echo "dtoverlay=i2c-rtc,pcf8523 already present (active) in ${CONFIG_FILE}."
else
  echo "Adding dtoverlay=i2c-rtc,pcf8523 to ${CONFIG_FILE}..."
  {
    echo ""
    echo "# PiCAN 3 Real Time Clock — PCF8523"
    echo "dtoverlay=i2c-rtc,pcf8523"
  } | sudo tee -a "${CONFIG_FILE}" > /dev/null
  ADDED=1
fi

if [[ "${ADDED}" -eq 1 ]]; then
  echo "RTC overlay config updated. Rebooting..."
  sudo reboot
fi

echo "RTC overlays already configured; no reboot needed."
