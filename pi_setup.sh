#!/usr/bin/env bash
set -euo pipefail

# ─── Setup sequence ────────────────────────────────────────────────────────────
# Edit this array to add, remove, or reorder setup steps.
# Scripts that trigger a reboot are marked; the script will wait for the Pi
# to come back online before continuing.
SETUP_SCRIPTS=(
    "raspberryPiSetup/set_hostname.sh"          # Set Pi hostname from PI_HOSTNAME (.env)
    "raspberryPiSetup/update.sh"                 # Update & upgrade packages — reboots if upgraded
    "raspberryPiSetup/install_CAN_utils.sh"      # Install can-utils
    "raspberryPiSetup/add_pican3_overlays.sh"    # PiCAN3 SPI/CAN overlays  — reboots if changed
    "raspberryPiSetup/enable_can0_at_startup.sh" # Configure can0 at boot
    
    # Real Time clock setup
    "raspberryPiSetup/install_rtc_tools.sh"      # Install i2c-tools
    "raspberryPiSetup/add_rtc_overlays.sh"       # RTC I2C overlays          — reboots if changed
    "raspberryPiSetup/disable_fake_hwclock.sh"   # Remove fake-hwclock
    
    "raspberryPiSetup/install_uv.sh"             # Install uv package manager
    "raspberryPiSetup/install_socketcand.sh"     # Build & install socketcand

    # WiFi AP (RaspAP) — guest QR; USB gadget remains admin/SSH uplink
    "raspberryPiSetup/install_raspap.sh"         # RaspAP Quick installer
    "raspberryPiSetup/configure_raspap_dual_ap.sh"  # Guest SSID + usb0 WAN
    "raspberryPiSetup/configure_ap_client_firewall.sh"  # Guest lockdown nftables
    "raspberryPiSetup/install_autopi_web_service.sh"    # collector + web on boot

    "raspberryPiSetup/print_network_map.sh"            # Final live network map
)
# ───────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: .env file not found." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${ENV_FILE}"

: "${PI_HOST:?PI_HOST must be set in .env}"
: "${PI_USER:?PI_USER must be set in .env}"
: "${PI_HOSTNAME:=autopi}"
: "${AP_SSID:=AUTOPI}"
: "${AP_HOSTNAME:=autopi.lan}"

REMOTE="${PI_USER}@${PI_HOST}"

wait_for_pi() {
    echo "  Waiting for Pi to come back online..."
    sleep 10
    until ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${REMOTE}" "true" 2>/dev/null; do
        echo "  Still waiting..."
        sleep 5
    done
    echo "  Pi is back online."
}

run_step() {
    local script="$1"
    local name
    name="$(basename "${script}")"

    echo ""
    echo "▶ ${name}"
    echo "────────────────────────────────"

    # Stream the script from this machine to the Pi over SSH stdin — no files need
    # to be present on the Pi first, so this is safe to run before deploy.sh.
    # Forward selected .env knobs so remote scripts can apply them.
    if ssh -o ConnectTimeout=10 "${REMOTE}" \
        "PI_HOSTNAME=$(printf '%q' "${PI_HOSTNAME}") AP_SSID=$(printf '%q' "${AP_SSID}") AP_HOSTNAME=$(printf '%q' "${AP_HOSTNAME}") bash -s" \
        < "${SCRIPT_DIR}/${script}"; then
        echo "✓ ${name} complete"
    else
        local exit_code=$?
        # Exit code 255 means SSH connection lost — likely a reboot
        if [[ ${exit_code} -eq 255 ]]; then
            echo "  Pi rebooted during ${name}."
            wait_for_pi
        else
            echo "Error: ${name} failed with exit code ${exit_code}." >&2
            exit "${exit_code}"
        fi
    fi
}

echo "Starting Pi setup for ${REMOTE}..."

for script in "${SETUP_SCRIPTS[@]}"; do
    run_step "${script}"
done

echo ""
echo "✓ Pi setup complete."
