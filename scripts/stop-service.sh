#!/bin/bash

################################################################################
# Wi-Lab Service Stop Script
#
# Stops the Wi-Lab systemd service.
#
# Usage: sudo bash scripts/stop-service.sh
################################################################################

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="$PROJECT_DIR/install"

# Import common logging functions
source "$INSTALL_DIR/common.sh"
export ROOT_HINT_SCRIPT="scripts/stop-service.sh"

# Require root
require_root

SERVICE_NAME="wi-lab.service"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

echo ""
log_header "Wi-Lab Service Stop"
echo ""

# Check service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    log_error "Service file not found at $SERVICE_FILE"
    log_info "Run: sudo bash install.sh"
    exit 1
fi

# Stop the service
log_info "Stopping service..."
if systemctl is-active --quiet $SERVICE_NAME; then
    systemctl stop $SERVICE_NAME
    log_success "Service stopped"
else
    log_warning "Service was not running"
fi

echo ""
