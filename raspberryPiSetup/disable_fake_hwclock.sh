#!/bin/bash
set -euo pipefail

UPDATED=0

echo "Uninstall fake-hwclock..."
if dpkg -s fake-hwclock &>/dev/null; then
  sudo apt-get -y remove fake-hwclock

  echo "Remove fake-hwclock service from startup..."
  sudo update-rc.d -f fake-hwclock remove || true

  echo "Disable fake-hwclock service..."
  sudo systemctl disable fake-hwclock || true
else
  echo "fake-hwclock not installed, skipping remove."
fi

# echo "Comment out systemd early-exit block in hwclock-set..."
# SCRIPT_LOCATION="/lib/udev/hwclock-set"
# FIRST_LINE='if [ -e /run/systemd/system ] ; then'
# COMMENTED_FIRST="#${FIRST_LINE}"

# if [[ ! -f "${SCRIPT_LOCATION}" ]]; then
#   echo "Error: ${SCRIPT_LOCATION} not found." >&2
#   exit 1
# fi

# LINE_NUM="$(grep -nFx "${FIRST_LINE}" "${SCRIPT_LOCATION}" | head -1 | cut -d: -f1 || true)"

# if [[ -n "${LINE_NUM}" ]]; then
#   END_LINE=$((LINE_NUM + 2))
#   sudo sed -i "${LINE_NUM},${END_LINE}s/^/#/" "${SCRIPT_LOCATION}"
#   echo "Commented out lines ${LINE_NUM}-${END_LINE} in ${SCRIPT_LOCATION}."
#   UPDATED=1
# elif grep -qFx "${COMMENTED_FIRST}" "${SCRIPT_LOCATION}"; then
#   echo "Systemd early-exit block already commented out in ${SCRIPT_LOCATION}."
# else
#   echo "Error: expected line not found in ${SCRIPT_LOCATION}:" >&2
#   echo "  ${FIRST_LINE}" >&2
#   exit 1
# fi

# comment_line_if_active() {
#   local label="$1"
#   local line="$2"
#   local commented="#${line}"
#   local num

#   num="$(grep -nFx "${line}" "${SCRIPT_LOCATION}" | head -1 | cut -d: -f1 || true)"
#   if [[ -n "${num}" ]]; then
#     sudo sed -i "${num}s/^/#/" "${SCRIPT_LOCATION}"
#     echo "Commented out ${label} on line ${num}."
#     UPDATED=1
#   elif grep -qFx "${commented}" "${SCRIPT_LOCATION}"; then
#     echo "${label} already commented out."
#   else
#     echo "Error: expected ${label} line not found in ${SCRIPT_LOCATION}:" >&2
#     echo "  ${line}" >&2
#     exit 1
#   fi
# }

# echo "Comment out 'badyear' line from config if it's not already commented out"
# comment_line_if_active "badyear" '/sbin/hwclock --rtc=$dev --systz --badyear'

# echo "Comment out 'systz' line from config if it's not already commented out"
# # Exact match so this does not also hit the --badyear line.
# comment_line_if_active "systz" '/sbin/hwclock --rtc=$dev --systz'

# if [[ "${UPDATED}" -eq 1 ]]; then
#   echo "hwclock-set was updated; rebooting..."
#   sudo reboot
# fi

# echo "fake-hwclock disable complete; no file changes, skipping reboot."
