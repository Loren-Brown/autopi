#!/usr/bin/env bash
# Set the Pi system hostname (mDNS → ${PI_HOSTNAME}.local).
# Default / override via PI_HOSTNAME from the laptop .env (exported by pi_setup.sh).
set -euo pipefail

PI_HOSTNAME="${PI_HOSTNAME:-autopi}"

# Hostname must be valid for Linux (letters, digits, hyphen).
if [[ ! "${PI_HOSTNAME}" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]]; then
  echo "Error: invalid PI_HOSTNAME='${PI_HOSTNAME}'" >&2
  exit 1
fi

current="$(hostname)"
if [[ "${current}" == "${PI_HOSTNAME}" ]]; then
  echo "Hostname already ${PI_HOSTNAME} — nothing to do."
  exit 0
fi

echo "Setting hostname: ${current} → ${PI_HOSTNAME}"
sudo hostnamectl set-hostname "${PI_HOSTNAME}"

# Keep /etc/hosts in sync so sudo and local resolves stay happy
if grep -qE '^127\.0\.1\.1[[:space:]]+' /etc/hosts; then
  sudo sed -i -E "s/^127\\.0\\.1\\.1.*/127.0.1.1\t${PI_HOSTNAME}/" /etc/hosts
else
  echo -e "127.0.1.1\t${PI_HOSTNAME}" | sudo tee -a /etc/hosts > /dev/null
fi

# Refresh mDNS if available
if systemctl list-unit-files avahi-daemon.service &>/dev/null; then
  sudo systemctl try-restart avahi-daemon.service 2>/dev/null || true
fi

echo "Hostname is now $(hostname) — use ${PI_HOSTNAME}.local from your laptop (.env PI_HOST)."
