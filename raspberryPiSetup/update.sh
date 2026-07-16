#!/bin/bash
set -euo pipefail

echo "Updating system packages..."
sudo apt-get update

UPGRADE_OUT="$(sudo apt-get upgrade -y)"
echo "${UPGRADE_OUT}"

if grep -qE '^0 upgraded,' <<< "${UPGRADE_OUT}"; then
  echo "No packages upgraded; skipping reboot."
  exit 0
fi

echo "Packages upgraded; rebooting..."
sudo reboot
