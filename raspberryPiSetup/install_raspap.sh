#!/usr/bin/env bash
# Install RaspAP via the official Quick installer (unattended).
# Docs: https://docs.raspap.com/quick/
set -euo pipefail

if [[ -d /var/www/html && -f /etc/raspap/raspap.php ]] || dpkg -s raspap &>/dev/null; then
  echo "RaspAP appears to be installed already, skipping Quick installer."
  exit 0
fi

if [[ -d /var/www/html/includes && -f /etc/lighttpd/lighttpd.conf ]]; then
  if grep -qR "RaspAP\|raspap" /var/www/html 2>/dev/null; then
    echo "RaspAP web files already present, skipping Quick installer."
    exit 0
  fi
fi

echo "Installing RaspAP (Quick installer, unattended)..."
echo "  Optional extras disabled: OpenVPN, WireGuard, Adblock, RestAPI"
curl -sL https://install.raspap.com | bash -s -- --yes \
  --openvpn 0 \
  --wireguard 0 \
  --adblock 0 \
  --restapi 0 \
  --provider 0 \
  --check 0

echo "RaspAP install finished."
echo "Next: configure_raspap_dual_ap.sh (dual SSID + usb0 uplink)."
