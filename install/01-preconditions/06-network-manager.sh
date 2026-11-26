#!/bin/bash

################################################################################
# Preconditions Stage 06: NetworkManager (NM-1)
#
# Wi-Lab requires Ubuntu Server with the host network on systemd-networkd.
# NetworkManager can take a Wi-Fi adapter back and bring a running AP down.
# - Not there, or already masked: nothing to do
# - Active but it manages the host network: never touch it, explain, ask
#   whether to continue outside the requirements
# - Active and managing nothing: explain, ask whether to disable and mask it,
#   check the default route and the gateway after, roll back if they are lost
#
# The package is never installed or removed.
#
# Usage: bash install/01-preconditions/06-network-manager.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

NM=NetworkManager.service

################################################################################
# Step 1: is it there?
################################################################################

nm_enabled=$(systemctl is-enabled "$NM" 2>/dev/null || true)
if [ "$nm_enabled" = "masked" ]; then
    state_set NM_STATE "masked"
    log_success "NetworkManager is masked"
    exit 0
fi
if ! systemctl is-active --quiet "$NM" && [ "$nm_enabled" != "enabled" ]; then
    state_set NM_STATE "absent"
    log_success "NetworkManager is not running"
    exit 0
fi

################################################################################
# Step 2: can it be disabled without losing access to this host?
################################################################################

default_devs() {
    ip -o route show default 2>/dev/null | awk '{for (i=1; i<NF; i++) if ($i=="dev") print $(i+1)}' | sort -u
}

nm_device_state() {  # state of $1 for NetworkManager, empty if unknown
    nmcli -t -f DEVICE,STATE device 2>/dev/null | awk -F: -v d="$1" '$1==d {print $2}'
}

networkd_setup() {   # SETUP column of networkctl for $1
    networkctl list --no-legend --no-pager 2>/dev/null | awk -v d="$1" '$2==d {print $5}'
}

failed=""
renderer=$(netplan get network.renderer 2>/dev/null || true)
if [ "$renderer" = "NetworkManager" ]; then
    failed="netplan uses NetworkManager as renderer"
fi

mapfile -t DEVS < <(default_devs)
if [ -z "$failed" ] && [ ${#DEVS[@]} -eq 0 ]; then
    failed="this host has no default route: cannot tell which interface gives access"
fi

if [ -z "$failed" ] && [ -n "$SSH_CONNECTION" ]; then
    ssh_ip=$(echo "$SSH_CONNECTION" | awk '{print $3}')
    ssh_dev=$(ip -o addr show 2>/dev/null | awk -v ip="$ssh_ip" '{split($4, a, "/"); if (a[1]==ip) print $2}' | head -1)
    if [ -n "$ssh_dev" ] && [[ ! " ${DEVS[*]} " =~ " $ssh_dev " ]]; then
        DEVS+=("$ssh_dev")
    fi
fi

if [ -z "$failed" ]; then
    for dev in "${DEVS[@]}"; do
        nm_state=$(nm_device_state "$dev")
        if [ "$nm_state" != "unmanaged" ]; then
            failed="$dev is ${nm_state:-unknown} for NetworkManager, not unmanaged"
            break
        fi
        if [ "$(networkd_setup "$dev")" != "configured" ]; then
            failed="$dev is not configured by systemd-networkd"
            break
        fi
    done
fi

if [ -z "$failed" ]; then
    busy=$(nmcli -t -f DEVICE,STATE device 2>/dev/null | awk -F: '$2=="connected" || $2 ~ /^connecting/ {print $1}' | xargs)
    if [ -n "$busy" ]; then
        failed="NetworkManager has connected devices: $busy"
    fi
fi

if [ -n "$failed" ]; then
    log_error "NetworkManager is active and cannot be disabled safely: $failed"
    echo "    NetworkManager manages the network of this host. Wi-Lab requires Ubuntu Server"
    echo "    with systemd-networkd. Move the host network to systemd-networkd (netplan"
    echo "    renderer: networkd) and run the installer again."
    echo ""
    echo -n "Continue the installation anyway, outside the requirements? (y/N) "
    read -r REPLY
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        state_set NM_STATE "active_blocked"
        exit 1
    fi
    state_set NM_STATE "active_unsupported"
    log_warning "NetworkManager left active: AP drops and failed recoveries are expected"
    exit 0
fi

################################################################################
# Step 3: explain and ask
################################################################################

echo "⚠️  NetworkManager is active on this host."
echo "    Wi-Lab does not use it. While it runs it can take a Wi-Fi adapter back"
echo "    (after its own restart or a USB reset) and bring a running AP down."
echo "    It manages no interface of this host: ${DEVS[*]} handled by systemd-networkd,"
echo "    so disabling it does not change the network access to this machine."
echo ""
echo -n "Disable NetworkManager now (systemctl disable --now + mask)? (y/N) "
read -r REPLY
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    state_set NM_STATE "active_declined"
    log_warning "NetworkManager left active: AP drops and failed recoveries are expected"
    exit 0
fi

################################################################################
# Step 4: disable
################################################################################

gateway=$(ip -o route show default 2>/dev/null | awk '{for (i=1; i<NF; i++) if ($i=="via") {print $(i+1); exit}}')
systemctl disable --now NetworkManager-wait-online.service NetworkManager-dispatcher.service "$NM" 2>/dev/null || true
systemctl mask "$NM"

################################################################################
# Step 5: check access, roll back if it is lost
################################################################################

ok=0
for _ in 1 2 3 4 5; do
    if [ -n "$(ip route show default 2>/dev/null)" ] && { [ -z "$gateway" ] || ping -c 1 -W 2 "$gateway" >/dev/null 2>&1; }; then
        ok=1
        break
    fi
    sleep 2
done

if [ $ok -ne 1 ]; then
    systemctl unmask "$NM" || true
    systemctl enable --now "$NM" || true
    state_set NM_STATE "rollback"
    log_error "Default route or gateway lost after disabling NetworkManager: re-enabled it"
    exit 1
fi

state_set NM_STATE "disabled"
log_success "NetworkManager disabled and masked; network access unchanged"
