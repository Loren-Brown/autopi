#!/usr/bin/env bash
# Live network map for autopi — how data flows to/from the Pi.
# Safe to re-run anytime (read-only aside from optional sudo for ap.env / nft).
set -euo pipefail

AP_ENV="/etc/autopi/ap.env"

# ── helpers ───────────────────────────────────────────────────────────────────
have() { command -v "$1" &>/dev/null; }

svc_state() {
  local u="$1"
  if systemctl list-unit-files "${u}" &>/dev/null || systemctl cat "${u}" &>/dev/null; then
    if systemctl is-active --quiet "${u}" 2>/dev/null; then
      echo "active"
    elif systemctl is-enabled --quiet "${u}" 2>/dev/null; then
      echo "inactive (enabled)"
    else
      echo "inactive"
    fi
  else
    echo "not installed"
  fi
}

iface_line() {
  local ifc="$1"
  if ! ip link show "${ifc}" &>/dev/null; then
    echo "  ${ifc}: (missing)"
    return
  fi
  local state addrs
  state="$(ip -o link show "${ifc}" | awk '{
    for (i=1;i<=NF;i++) if ($i ~ /^state$/) { print $(i+1); exit }
  }')"
  addrs="$(ip -4 -o addr show "${ifc}" 2>/dev/null | awk '{print $4}' | paste -sd', ' -)"
  [[ -z "${addrs}" ]] && addrs="(no IPv4)"
  echo "  ${ifc}: ${state}  ${addrs}"
}

load_ap_env() {
  GUEST_SSID="AUTOPI"
  ADMIN_SSID="autopi-admin"
  GUEST_GATEWAY="10.3.141.1"
  ADMIN_GATEWAY="10.3.142.1"
  GUEST_SUBNET="10.3.141.0/24"
  ADMIN_SUBNET="10.3.142.0/24"
  WAN_IFACE="usb0"
  if [[ -f "${AP_ENV}" ]]; then
    if [[ -r "${AP_ENV}" ]]; then
      # shellcheck source=/dev/null
      source "${AP_ENV}"
    elif have sudo; then
      # shellcheck source=/dev/null
      source <(sudo cat "${AP_ENV}" 2>/dev/null || true)
    fi
  fi
}

default_route_info() {
  ip -4 route show default 2>/dev/null | head -n1 || true
}

wan_status() {
  local wan="${WAN_IFACE:-usb0}"
  local def method gw src via
  def="$(default_route_info)"
  via=""
  gw=""
  src=""
  if [[ -n "${def}" ]]; then
    via="$(awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}' <<<"${def}")"
    gw="$(awk '{for(i=1;i<=NF;i++) if($i=="via"){print $(i+1); exit}}' <<<"${def}")"
    src="$(awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' <<<"${def}")"
  fi

  method="unknown"
  if have nmcli && ip link show "${wan}" &>/dev/null; then
    local con
    con="$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null | awk -F: -v d="${wan}" '$2==d {print $1; exit}')"
    if [[ -n "${con}" ]]; then
      method="$(nmcli -g ipv4.method connection show "${con}" 2>/dev/null || echo unknown)"
      echo "  NM profile: ${con}  (ipv4.method=${method})"
      if [[ "${method}" == "shared" ]]; then
        echo "  ⚠ WARNING: ${wan} is SHARED — Mac may route internet into the Pi and lose uplink."
        echo "    Re-run configure_raspap_dual_ap.sh to switch to DHCP client."
      fi
    else
      echo "  NM profile: (none active on ${wan})"
    fi
  fi

  if [[ -z "${def}" ]]; then
    echo "  Default route: (none) — Pi has no upstream internet right now"
  else
    echo "  Default route: ${def}"
    if [[ "${via}" == "${wan}" ]]; then
      echo "  Internet via: ${wan} (expected Mac USB uplink)"
      [[ -n "${gw}" ]] && echo "  Gateway: ${gw}  (Mac Internet Sharing / DHCP)"
      [[ -n "${src}" ]] && echo "  Pi address on WAN: ${src}"
    elif [[ -n "${via}" ]]; then
      echo "  Internet via: ${via}  (not ${wan} — check WiFi client / Ethernet)"
    fi
  fi

  # Quick egress check (best-effort, non-fatal)
  if have ping; then
    if ping -c1 -W2 1.1.1.1 &>/dev/null; then
      echo "  Egress check: OK (ping 1.1.1.1)"
    else
      echo "  Egress check: FAIL (no reply from 1.1.1.1)"
      echo "    Tip: on Mac enable Internet Sharing → USB, or join admin AP with another uplink."
    fi
  fi
}

print_diagram() {
  local wan="${WAN_IFACE:-usb0}"
  local guest_ssid="${GUEST_SSID:-AUTOPI}"
  local admin_ssid="${ADMIN_SSID:-autopi-admin}"
  local guest_gw="${GUEST_GATEWAY:-10.3.141.1}"
  local admin_gw="${ADMIN_GATEWAY:-10.3.142.1}"
  local usb_ip
  usb_ip="$(ip -4 -o addr show "${wan}" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)"
  [[ -z "${usb_ip}" ]] && usb_ip="(no IPv4)"

  cat <<EOF

╔══════════════════════════════════════════════════════════════════════════════╗
║                         autopi NETWORK MAP                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

  Internet
      │
      ▼
  ┌─────────────┐  Internet Sharing / DHCP     ┌──────────────────────────────┐
  │  Mac / WAN  │ ───────────────────────────► │  Pi ${wan}  ${usb_ip}         │
  │             │ ◄── SSH :22 / web :8080 ──── │  (DHCP client of Mac)        │
  └─────────────┘                              └──────────────┬───────────────┘
                                                              │
                    ┌─────────────────────────────────────────┼─────────────────┐
                    │                                         │                 │
                    ▼                                         ▼                 ▼
           ┌────────────────┐                      ┌────────────────┐   ┌──────────────┐
           │  Guest AP      │                      │  Admin AP      │   │  can0        │
           │  ${guest_ssid} │                      │  ${admin_ssid} │   │  PiCAN3/SSM  │
           │  ${guest_gw}/24│                      │  ${admin_gw}/24│   │  socketcand  │
           └───────┬────────┘                      └───────┬────────┘   └──────┬───────┘
                   │                                       │                   │
                   │  TCP 8080 + 8090 only                 │  full access      │
                   │  (nftables lock)                      │  + NAT out ${wan} │  SSM / OBD
                   ▼                                       ▼                   ▼
              Phone / tablet                          Laptop (admin)      ECU / Teensy
              → http://${guest_gw}:8080               → SSH, RaspAP, GUI

  Data paths
  ──────────
  • Mac ↔ Pi (USB): SSH, dashboard, deploy — L3 on ${wan}
  • Guest WiFi → Pi: dashboard :8080 + collector WS :8090 only (no internet, no SSH)
  • Admin WiFi → Pi: full local access; client traffic may NAT out via ${wan}
  • Pi internet: default route should be ${wan} ← Mac (not Pi shared → Mac)
  • CAN: can0 ↔ socketcand (:29536) ↔ app / SSH tunnel

EOF
}

print_interfaces() {
  echo "── Interfaces ────────────────────────────────────────────────────────────"
  for ifc in lo eth0 wlan0 wlan0_1 usb0 can0; do
    iface_line "${ifc}"
  done
  # Any other non-lo interfaces
  while read -r ifc; do
    case "${ifc}" in
      lo|eth0|wlan0|wlan0_1|usb0|can0) continue ;;
      *) iface_line "${ifc}" ;;
    esac
  done < <(ip -o link show | awk -F': ' '{print $2}' | cut -d@ -f1)
  echo ""
}

print_wan() {
  echo "── Pi internet / WAN (${WAN_IFACE:-usb0}) ─────────────────────────────────"
  wan_status
  echo ""
}

print_aps() {
  echo "── WiFi access points ────────────────────────────────────────────────────"
  if [[ -f "${AP_ENV}" ]]; then
    echo "  Config: ${AP_ENV}"
    echo "  Guest  SSID=${GUEST_SSID}  gw=${GUEST_GATEWAY}  subnet=${GUEST_SUBNET}"
    echo "  Admin  SSID=${ADMIN_SSID}  gw=${ADMIN_GATEWAY}  subnet=${ADMIN_SUBNET}"
    echo "  WAN_IFACE=${WAN_IFACE}"
    if [[ -n "${GUEST_PSK:-}" ]]; then
      echo "  Guest PSK: ${GUEST_PSK}"
    fi
    if [[ -n "${ADMIN_PSK:-}" ]]; then
      echo "  Admin PSK: ${ADMIN_PSK}"
    fi
  else
    echo "  Config: ${AP_ENV} missing — dual AP not configured yet"
  fi
  echo "  hostapd: $(svc_state hostapd.service)"
  echo "  dnsmasq: $(svc_state dnsmasq.service)"
  echo "  wlan addrs: $(svc_state autopi-wlan-addrs.service)"
  echo "  AP firewall: $(svc_state autopi-ap-firewall.service)"

  if have iw; then
    local n
    n="$(iw dev wlan0 station dump 2>/dev/null | grep -c '^Station' || true)"
    echo "  Guest clients (wlan0): ${n}"
    if ip link show wlan0_1 &>/dev/null; then
      n="$(iw dev wlan0_1 station dump 2>/dev/null | grep -c '^Station' || true)"
      echo "  Admin clients (wlan0_1): ${n}"
    fi
  fi

  if [[ -r /var/lib/misc/dnsmasq.leases ]] || sudo test -r /var/lib/misc/dnsmasq.leases 2>/dev/null; then
    echo "  DHCP leases:"
    (cat /var/lib/misc/dnsmasq.leases 2>/dev/null || sudo cat /var/lib/misc/dnsmasq.leases 2>/dev/null || true) \
      | awk 'NF>=4 {printf "    %s  %s  %s\n", $3, $2, $4}' || echo "    (none)"
  fi
  echo ""
}

print_firewall() {
  echo "── Guest / admin firewall (nftables) ─────────────────────────────────────"
  if have nft; then
    if sudo nft list table inet autopi_ap &>/dev/null; then
      echo "  table inet autopi_ap: present"
      echo "  Guest (wlan0): allow TCP 8080,8090 + DHCP/DNS; drop everything else"
      echo "  Guest forward → ${WAN_IFACE}: drop (no internet)"
      echo "  Admin (wlan0_1): accept; NAT masquerade out ${WAN_IFACE}"
    else
      echo "  table inet autopi_ap: missing — run configure_ap_client_firewall.sh"
    fi
  else
    echo "  nft not installed"
  fi
  echo ""
}

print_services() {
  echo "── Services ──────────────────────────────────────────────────────────────"
  printf "  %-28s %s\n" "autopi-web.service" "$(svc_state autopi-web.service)"
  printf "  %-28s %s\n" "autopi-collector.service" "$(svc_state autopi-collector.service)"
  printf "  %-28s %s\n" "socketcand.service" "$(svc_state socketcand.service)"
  printf "  %-28s %s\n" "ssh.service" "$(svc_state ssh.service)"
  printf "  %-28s %s\n" "NetworkManager.service" "$(svc_state NetworkManager.service)"
  echo ""
}

print_listeners() {
  echo "── Listening ports (Pi) ──────────────────────────────────────────────────"
  if have ss; then
    ss -lntu 2>/dev/null | awk 'NR==1 || /:(22|53|67|80|443|8080|8090|29536)\s/' \
      || ss -lntu | head -n 20
  else
    echo "  ss not available"
  fi
  echo ""
  echo "  Reachability cheatsheet:"
  local usb_ip guest_gw admin_gw
  usb_ip="$(ip -4 -o addr show "${WAN_IFACE:-usb0}" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)"
  guest_gw="${GUEST_GATEWAY:-10.3.141.1}"
  admin_gw="${ADMIN_GATEWAY:-10.3.142.1}"
  echo "    Mac over USB:     http://${usb_ip:-<usb0-ip>}:8080   ssh ${USER}@${usb_ip:-<usb0-ip>}"
  echo "    Guest WiFi:       http://${guest_gw}:8080            (no SSH)"
  echo "    Admin WiFi:       http://${admin_gw}:8080            ssh ${USER}@${admin_gw}"
  echo "    mDNS (any path):  http://$(hostname).local:8080"
  echo ""
}

print_ssh() {
  echo "── Active SSH sessions ───────────────────────────────────────────────────"
  if have who; then
    echo "  Logged-in users:"
    local wh
    wh="$(who 2>/dev/null || true)"
    if [[ -n "${wh}" ]]; then
      echo "${wh}" | sed 's/^/    /'
    else
      echo "    (none)"
    fi
  fi
  if have ss; then
    local peers
    peers="$(ss -H -tnp state established '( sport = :22 )' 2>/dev/null || true)"
    if [[ -z "${peers}" ]]; then
      echo "  (no established SSH connections right now)"
    else
      echo "  SSH peers:"
      while read -r _ _ _ _local rem _rest; do
        [[ -z "${rem:-}" ]] && continue
        # Strip port (IPv4 host:port or [ipv6]:port)
        local peer path
        peer="${rem%:*}"
        peer="${peer#[}"
        peer="${peer%]}"
        path="other"
        case "${peer}" in
          10.3.141.*) path="guest AP (unexpected — guest firewall should block SSH)" ;;
          10.3.142.*) path="admin AP" ;;
          192.168.2.*|192.168.137.*|10.12.194.*) path="USB gadget (Mac)" ;;
          169.254.*) path="link-local (USB/other)" ;;
        esac
        echo "    ${peer}  ←  ${path}"
      done <<<"${peers}"
    fi
  fi
  echo ""
}

print_can() {
  echo "── CAN bus ───────────────────────────────────────────────────────────────"
  if ip link show can0 &>/dev/null; then
    ip -details link show can0 2>/dev/null | sed 's/^/  /' | head -n 6
    if have candump; then
      echo "  can-utils: installed"
    fi
  else
    echo "  can0: not present"
  fi
  echo "  socketcand: $(svc_state socketcand.service)  (TCP 29536)"
  echo ""
}

# ── main ──────────────────────────────────────────────────────────────────────
load_ap_env
HOST="$(hostname 2>/dev/null || echo pi)"
WHEN="$(date -Is 2>/dev/null || date)"

echo "Generated on ${HOST} at ${WHEN}"
print_diagram
print_interfaces
print_wan
print_aps
print_firewall
print_services
print_listeners
print_ssh
print_can

echo "════════════════════════════════════════════════════════════════════════════"
echo "Re-run anytime:  ssh ${USER}@${HOST} 'bash -s' < raspberryPiSetup/print_network_map.sh"
echo "════════════════════════════════════════════════════════════════════════════"
