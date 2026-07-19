#!/bin/bash
set -euo pipefail

# Package install only — does not reboot. Overlay reboot is add_pican3_overlays.sh.

if dpkg -s can-utils &>/dev/null; then
  echo "can-utils already installed, skipping."
  exit 0
fi

echo "Installing CAN Utils..."
sudo DEBIAN_FRONTEND=noninteractive apt-get install can-utils -y
echo "can-utils installed (no reboot required)."
