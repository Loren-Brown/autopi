#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

# Need DNS for apt mirrors. IP connectivity alone is not enough (empty resolv.conf).
if ! getent hosts deb.debian.org >/dev/null 2>&1; then
  echo "Cannot resolve deb.debian.org — skipping package update."
  if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
    echo "  IP uplink works, but DNS is broken (often empty /etc/resolv.conf)."
    echo "  Fix: run raspberryPiSetup/configure_wan_dns.sh (or re-run ./pi_setup.sh)."
  else
    echo "  No IP uplink either — enable Mac Internet Sharing to usb0, then re-run."
  fi
  exit 0
fi

echo "Updating system packages..."
sudo DEBIAN_FRONTEND=noninteractive apt-get update

UPGRADE_OUT="$(sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y)"
echo "${UPGRADE_OUT}"

# Reboot only when apt-get reports at least one package upgraded.
if grep -qE '(^|[[:space:]])[1-9][0-9]* upgraded,' <<< "${UPGRADE_OUT}"; then
  echo "Packages upgraded; rebooting..."
  sudo reboot
fi

echo "No packages upgraded; skipping reboot."
