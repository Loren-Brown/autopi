#!/usr/bin/env bash
# Ensure the Pi itself can resolve names when usb0 has IP connectivity.
#
# RaspAP/hostapd leaves wlan0 unmanaged; NetworkManager still owns
# /etc/resolv.conf and often writes an empty file when no NM profile
# supplies DNS — even though dhcpcd already has nameservers configured.
# Guests keep using dnsmasq on 10.3.141.1; this only fixes Pi-local DNS.
set -euo pipefail

NM_DNS_CONF="/etc/NetworkManager/conf.d/90-autopi-dns.conf"
RESOLV="/etc/resolv.conf"
DNS_PRIMARY="${AUTOPI_DNS_PRIMARY:-9.9.9.9}"
DNS_SECONDARY="${AUTOPI_DNS_SECONDARY:-1.1.1.1}"

echo "Configuring Pi WAN DNS (NetworkManager must not blank resolv.conf)..."

sudo mkdir -p /etc/NetworkManager/conf.d
sudo tee "${NM_DNS_CONF}" > /dev/null <<'EOF'
# autopi — do not let NM overwrite /etc/resolv.conf with an empty file.
# dhcpcd (usb0 DHCP from Mac Internet Sharing) supplies / manages DNS.
[main]
dns=none
rc-manager=unmanaged
EOF

# Keep dhcpcd fallbacks in sync (idempotent).
if [[ -f /etc/dhcpcd.conf ]]; then
  if ! grep -qE '^[[:space:]]*static domain_name_servers=' /etc/dhcpcd.conf; then
    echo "static domain_name_servers=${DNS_PRIMARY} ${DNS_SECONDARY}" | sudo tee -a /etc/dhcpcd.conf > /dev/null
    echo "  Added static domain_name_servers to /etc/dhcpcd.conf"
  else
    echo "  dhcpcd static domain_name_servers already set"
  fi
fi

sudo tee "${RESOLV}" > /dev/null <<EOF
# autopi WAN DNS — managed by configure_wan_dns.sh (NM rc-manager=unmanaged)
nameserver ${DNS_PRIMARY}
nameserver ${DNS_SECONDARY}
EOF
echo "  Wrote ${RESOLV} → ${DNS_PRIMARY}, ${DNS_SECONDARY}"

if systemctl is-active NetworkManager >/dev/null 2>&1; then
  sudo systemctl reload NetworkManager 2>/dev/null \
    || sudo nmcli general reload conf 2>/dev/null \
    || true
fi

if getent hosts deb.debian.org >/dev/null 2>&1; then
  echo "DNS OK: deb.debian.org resolves"
else
  echo "DNS still failing — check usb0 uplink / firewall; resolv.conf is:" >&2
  cat "${RESOLV}" >&2 || true
  exit 1
fi
