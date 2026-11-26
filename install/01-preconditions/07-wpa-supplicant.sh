#!/bin/bash

################################################################################
# Preconditions Stage 07: wpa_supplicant (NM-1)
#
# Wi-Lab does not use wpa_supplicant (the APs run on hostapd). It is a D-Bus
# service: any program can ask it to manage a Wi-Fi adapter, and then it
# competes with hostapd on that radio.
# - Not there, or already masked: nothing to do
# - NetworkManager still active: leave it, NetworkManager needs it
# - The host uses it as a Wi-Fi client: leave it, explain why
# - Otherwise: explain, ask whether to disable and mask it
#
# The package is never removed.
#
# Usage: bash install/01-preconditions/07-wpa-supplicant.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

WPA=wpa_supplicant.service

################################################################################
# Step 1: anything to ask?
################################################################################

wpa_enabled=$(systemctl is-enabled "$WPA" 2>/dev/null || true)
if [ "$wpa_enabled" = "masked" ]; then
    state_set WPA_STATE "masked"
    log_success "wpa_supplicant is masked"
    exit 0
fi
if ! systemctl is-active --quiet "$WPA" && [ "$wpa_enabled" != "enabled" ]; then
    state_set WPA_STATE "absent"
    log_success "wpa_supplicant is not running"
    exit 0
fi
if systemctl is-active --quiet NetworkManager.service; then
    state_set WPA_STATE "kept_nm_active"
    log_info "wpa_supplicant left as it is: NetworkManager is active"
    exit 0
fi

################################################################################
# Step 2: does the host use it as a Wi-Fi client?
################################################################################

in_use=""
wifis=$(netplan get network.wifis 2>/dev/null || true)
if [ -n "$wifis" ] && [ "$wifis" != "null" ] && [ "$wifis" != "{}" ]; then
    in_use="netplan has Wi-Fi networks"
fi
if [ -z "$in_use" ]; then
    units=$(systemctl list-units --state=active --no-legend --plain 'netplan-wpa-*' 'wpa_supplicant@*' 2>/dev/null | awk '{print $1}' | xargs)
    [ -n "$units" ] && in_use="client units are active: $units"
fi
if [ -z "$in_use" ]; then
    for dev in $(ip -o route show default 2>/dev/null | awk '{for (i=1; i<NF; i++) if ($i=="dev") print $(i+1)}' | sort -u); do
        if [ -e "/sys/class/net/$dev/wireless" ]; then
            in_use="the default route goes through the Wi-Fi interface $dev"
            break
        fi
    done
fi
if [ -n "$in_use" ]; then
    state_set WPA_STATE "in_use"
    log_warning "wpa_supplicant left active: $in_use"
    exit 0
fi

################################################################################
# Step 3: explain and ask
################################################################################

echo "⚠️  wpa_supplicant is active on this host."
echo "    Wi-Lab does not use it (the APs run on hostapd). If a program asks it to"
echo "    manage a Wi-Fi adapter, it competes with hostapd on that radio."
echo "    No Wi-Fi client connection of this host uses it."
echo ""
echo -n "Disable wpa_supplicant now (systemctl disable --now + mask)? (y/N) "
read -r REPLY
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    state_set WPA_STATE "active_declined"
    log_warning "wpa_supplicant left active: it may take a Wi-Lab radio if a program asks it to"
    exit 0
fi

################################################################################
# Step 4: disable
################################################################################

systemctl disable --now "$WPA" 2>/dev/null || true
systemctl mask "$WPA"
state_set WPA_STATE "disabled"
log_success "wpa_supplicant disabled and masked"
