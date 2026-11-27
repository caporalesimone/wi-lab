#!/bin/bash

################################################################################
# Wi-Lab Uninstall Script
# 
# This script removes Wi-Lab installation:
# 1. Stops the wi-lab service
# 2. Disables systemd auto-start
# 3. Removes systemd unit file
# 4. Removes Wi-Lab firewall rules, runtime files and devices
# 5. Offers to re-enable NetworkManager / wpa_supplicant if they are masked
# 6. Removes the Python virtual environment
#
# Usage: sudo bash uninstall.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR/install"

# Import common logging functions
source "$INSTALL_DIR/common.sh"
export ROOT_HINT_SCRIPT="uninstall.sh"
install_common_vars

SERVICE_FILE="/etc/systemd/system/wi-lab.service"

require_root

echo ""
log_header "Wi-Lab Uninstall - Preview"
echo ""
echo "This uninstall script will:"
echo ""
echo "  1. Stop the wi-lab service"
echo "  2. Disable autostart on boot"
echo "  3. Remove systemd unit file at $SERVICE_FILE"
echo "  4. Remove Wi-Lab firewall rules, runtime files and QoS devices left on the host"
echo "  5. Offer to re-enable NetworkManager and wpa_supplicant if they are masked"
echo "  6. Remove Python virtual environment at $VENV_PATH"
echo ""
echo "Note:"
echo "  - Config file (config.yaml) will REMAIN in $WILAB_DIR"
echo "  - Project files will REMAIN in $WILAB_DIR"
echo "  - To remove all files: sudo rm -rf $WILAB_DIR"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -n "Proceed with uninstall? (y/N) "
read -r REPLY
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_info "Uninstall cancelled"
    exit 0
fi

echo ""
log_info "Wi-Lab Uninstall - Starting..."
echo ""

################################################################################
# STEP 1: Stop and disable service
################################################################################

if command -v systemctl >/dev/null 2>&1; then
    log_info "Step 1: Stopping and disabling service..."
    systemctl stop wi-lab.service 2>/dev/null || log_warning "Service not running"
    systemctl disable wi-lab.service 2>/dev/null || log_warning "Service not enabled"

    if [ -f "$SERVICE_FILE" ]; then
        log_info "Removing systemd unit..."
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
        log_success "Systemd unit removed"
    else
        log_warning "No systemd unit found at $SERVICE_FILE"
    fi
else
    log_warning "systemctl not available; skipping service removal"
fi

echo ""

################################################################################
# STEP 2: Remove Docker image and containers
################################################################################

if command -v docker >/dev/null 2>&1; then
    log_info "Step 2: Removing Docker frontend build image and containers..."
    
    # Extract IMAGE_NAME from deploy_frontend.sh to stay in sync
    DEPLOY_SCRIPT="$WILAB_DIR/frontend/deploy_frontend.sh"
    if [ -f "$DEPLOY_SCRIPT" ]; then
        DOCKER_IMAGE=$(grep '^IMAGE_NAME=' "$DEPLOY_SCRIPT" | cut -d'"' -f2)
        
        if [ -n "$DOCKER_IMAGE" ]; then
            # Remove any running containers from this image
            if docker ps -a --format '{{.Image}}' | grep -q "^${DOCKER_IMAGE}$"; then
                log_info "Removing containers from $DOCKER_IMAGE..."
                docker ps -a --filter "ancestor=${DOCKER_IMAGE}" -q | xargs -r docker rm -f 2>/dev/null || true
                log_success "Containers removed"
            fi
            
            # Remove the image
            if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${DOCKER_IMAGE}$"; then
                log_info "Removing Docker image: $DOCKER_IMAGE..."
                docker rmi -f "$DOCKER_IMAGE" 2>/dev/null || log_warning "Failed to remove Docker image"
                log_success "Docker image removed"
            else
                log_info "Docker image $DOCKER_IMAGE not found"
            fi
        else
            log_warning "Could not extract IMAGE_NAME from $DEPLOY_SCRIPT"
        fi
    else
        log_info "Deploy script not found at $DEPLOY_SCRIPT; skipping Docker image removal"
    fi
else
    log_info "Step 2: Docker not found; skipping Docker cleanup"
fi

echo ""

################################################################################
# STEP 3: Remove what a stopped service may leave on the host
################################################################################

# Stopping the service releases every network, but some state outlives it: the
# wilab-protect-existing FORWARD rule, runtime directories, the systemd-networkd
# rule that keeps the radios unmanaged, QoS IFB devices.
log_info "Step 3: Removing Wi-Lab firewall rules, runtime files and devices..."
for cmd in iptables ip6tables; do
    command -v "$cmd" >/dev/null 2>&1 || continue
    for table in filter nat mangle; do
        # Rules first (they may jump to Wi-Lab chains), then the chains.
        "$cmd" -w 5 -t "$table" -S 2>/dev/null | grep -- '--comment wilab-' | sed 's/^-A /-D /' |
            while read -r rule; do
                eval "$cmd -w 5 -t $table $rule" 2>/dev/null || true
            done
        "$cmd" -w 5 -t "$table" -S 2>/dev/null | grep -E -- '-j wilab-(in|cp)-' | sed 's/^-A /-D /' |
            while read -r rule; do
                eval "$cmd -w 5 -t $table $rule" 2>/dev/null || true
            done
        "$cmd" -w 5 -t "$table" -S 2>/dev/null | awk '$1 == "-N" && $2 ~ /^wilab-(in|cp)-/ {print $2}' |
            while read -r chain; do
                "$cmd" -w 5 -t "$table" -F "$chain" 2>/dev/null || true
                "$cmd" -w 5 -t "$table" -X "$chain" 2>/dev/null || true
            done
    done
done
for dev in $(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | cut -d@ -f1 | grep '^wilab-ifb'); do
    ip link del "$dev" 2>/dev/null || true
done
rm -rf /run/wilab /tmp/wilab-hostapd /tmp/wilab-dnsmasq   # /tmp: before 4.1.0
rm -f /etc/needrestart/conf.d/wilab.conf   # the installer's needrestart exclusion
if [ -f /run/systemd/network/00-wilab-unmanaged.network ]; then
    rm -f /run/systemd/network/00-wilab-unmanaged.network
    networkctl reload 2>/dev/null || true
fi
# grep -c exits 1 on zero matches, and common.sh sets -e: never let it end the script.
left=$(for cmd in iptables ip6tables; do for t in filter nat mangle; do "$cmd" -w 5 -t "$t" -S 2>/dev/null; done; done | grep -c 'wilab-' || true)
if [ "$left" -eq 0 ]; then
    log_success "No Wi-Lab rule, runtime file or device left"
else
    log_warning "$left Wi-Lab firewall entries could not be removed: check with iptables -S | grep wilab"
fi

echo ""

################################################################################
# STEP 4: Offer to re-enable services the installer masked (NM-1)
################################################################################

# The installer may have disabled and masked them (stages 06 and 07). Its state
# file is in /tmp and does not survive a reboot: ask for every masked one.
# wpa_supplicant first: NetworkManager needs it for Wi-Fi.
if command -v systemctl >/dev/null 2>&1; then
    log_info "Step 4: Checking services the installer may have masked..."
    for unit in wpa_supplicant.service NetworkManager.service; do
        if [ "$(systemctl is-enabled "$unit" 2>/dev/null || true)" != "masked" ]; then
            continue
        fi
        echo -n "$unit is masked (the Wi-Lab installer may have done it). Re-enable it? (y/N) "
        read -r REPLY
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if systemctl unmask "$unit" && systemctl enable --now "$unit"; then
                log_success "$unit re-enabled"
            else
                log_warning "Could not re-enable $unit"
            fi
        else
            log_info "$unit left masked"
        fi
    done
fi

echo ""

################################################################################
# STEP 5: Remove virtual environment (MANDATORY)
################################################################################

log_info "Step 5: Removing virtual environment..."
if [ -d "$VENV_PATH" ]; then
    log_info "Removing virtual environment..."
    rm -rf "$VENV_PATH"
    log_success "Virtual environment removed"
else
    log_warning "Virtual environment not found at $VENV_PATH"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log_success "Wi-Lab uninstall completed! 🎉"
echo ""
log_info "Note:"
echo "  - Config file remains at: $WILAB_DIR/config.yaml"
echo "  - Project files remain at: $WILAB_DIR"
echo "  - To remove all files: sudo rm -rf $WILAB_DIR"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
