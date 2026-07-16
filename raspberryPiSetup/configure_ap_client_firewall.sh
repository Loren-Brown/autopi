#!/usr/bin/env bash
# nftables: guest AP locked to autopi GUI; usb0 untouched.
set -euo pipefail

AP_ENV="/etc/autopi/ap.env"
NFT_FILE="/etc/nftables.d/autopi-ap.nft"
APPLY_SCRIPT="/usr/local/sbin/autopi-ap-firewall.sh"
SERVICE="/etc/systemd/system/autopi-ap-firewall.service"

if [[ -f "${AP_ENV}" ]]; then
  if [[ -r "${AP_ENV}" ]]; then
    # shellcheck source=/dev/null
    source "${AP_ENV}"
  else
    # shellcheck source=/dev/null
    source <(sudo cat "${AP_ENV}")
  fi
fi

GUEST_GATEWAY="${GUEST_GATEWAY:-10.3.141.1}"
GUEST_SUBNET="${GUEST_SUBNET:-10.3.141.0/24}"
WAN_IFACE="${WAN_IFACE:-usb0}"

sudo mkdir -p /etc/nftables.d

sudo tee "${NFT_FILE}" > /dev/null <<EOF
#!/usr/sbin/nft -f
# autopi AP client policy — managed by configure_ap_client_firewall.sh
# Guest (wlan0): TCP 80/8080/8090 + DHCP/DNS only; port 80 → 8080 for captive/phones
# usb0: no extra denies (Mac admin path)

table inet autopi_ap {
  chain prerouting {
    type nat hook prerouting priority dstnat; policy accept;
    # Phones probe captive portals on :80; dashboard listens on :8080
    iifname "wlan0" tcp dport 80 redirect to :8080
  }

  chain input {
    type filter hook input priority 0; policy accept;

    iifname "wlan0" tcp dport { 80, 8080, 8090 } accept
    iifname "wlan0" udp dport 67 accept
    iifname "wlan0" udp dport 53 accept
    iifname "wlan0" tcp dport 53 accept
    iifname "wlan0" icmp type echo-request accept
    iifname "wlan0" ct state established,related accept
    iifname "wlan0" drop
  }

  chain forward {
    type filter hook forward priority 0; policy accept;

    iifname "wlan0" oifname "${WAN_IFACE}" drop
    iifname "wlan0" drop
  }
}
EOF

sudo tee "${APPLY_SCRIPT}" > /dev/null <<EOF
#!/usr/bin/env bash
set -euo pipefail
sleep 2
/usr/sbin/nft delete table inet autopi_ap 2>/dev/null || true
/usr/sbin/nft -f ${NFT_FILE}
EOF
sudo chmod +x "${APPLY_SCRIPT}"

sudo tee "${SERVICE}" > /dev/null <<EOF
[Unit]
Description=autopi AP client firewall (guest lockdown)
After=autopi-wlan-addrs.service hostapd.service network-online.target
Wants=autopi-wlan-addrs.service

[Service]
Type=oneshot
ExecStart=${APPLY_SCRIPT}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable autopi-ap-firewall.service
sudo "${APPLY_SCRIPT}"

echo "AP firewall applied:"
echo "  Guest  ${GUEST_SUBNET} (wlan0)  → TCP 80/8080/8090 (80→8080), DHCP/DNS; no forward"
echo "  Admin  USB gadget / eth — full access"
echo "  Rules: ${NFT_FILE}"
