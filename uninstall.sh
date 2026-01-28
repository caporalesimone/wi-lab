#!/bin/bash

################################################################################
# Wi-Lab Uninstall Script
# 
# This script removes Wi-Lab installation:
# 1. Stops the wi-lab service
# 2. Disables systemd auto-start
# 3. Removes systemd unit file
# 4. Optionally removes Python virtual environment
#
# Usage: sudo bash uninstall.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_DIR="$SCRIPT_DIR/setup"

# Import common logging functions
source "$SETUP_DIR/common.sh"
setup_common_vars

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
echo "  4. Remove Python virtual environment at $VENV_PATH"
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
# STEP 2: Remove virtual environment (MANDATORY)
################################################################################

log_info "Step 2: Removing virtual environment..."
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
