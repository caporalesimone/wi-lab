#!/bin/bash

################################################################################
# Preconditions Stage 05: Network Interface
# 
# Checks:
# - WiFi interface defined in config
# - WiFi interface is available on host
#
# Usage: bash install/01-preconditions/05-network.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

################################################################################
# Extract WiFi interface from config
################################################################################

WIFI_IFACE=$(grep -E "^\s+interface:" "$WILAB_DIR/config.yaml" 2>/dev/null | head -1 | sed -E 's/.*interface:\s*"?([^"]+)"?.*/\1/' | xargs)

if [ -z "$WIFI_IFACE" ]; then
    state_set NETWORK_AP_INTERFACE ""
    state_set NETWORK_AP_INTERFACE_EXISTS "0"
    log_error "No WiFi interface found in config.yaml"
    exit 1
fi

state_set NETWORK_AP_INTERFACE "$WIFI_IFACE"
log_info "WiFi interface configured: $WIFI_IFACE"

################################################################################
# Verify WiFi interface is available
################################################################################

if ! ip link show "$WIFI_IFACE" &>/dev/null; then
    state_set NETWORK_AP_INTERFACE_EXISTS "0"
    log_warning "WiFi interface $WIFI_IFACE not found on host"
    log_info "  (This is OK if it's in a namespace already)"
else
    state_set NETWORK_AP_INTERFACE_EXISTS "1"
    log_success "WiFi interface $WIFI_IFACE is available"
fi

log_success "Network interface requirements satisfied"
