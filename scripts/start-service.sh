#!/bin/bash

################################################################################
# Wi-Lab Service Start Script
#
# Starts the Wi-Lab systemd service and displays status.
#
# Usage: sudo bash scripts/start-service.sh
################################################################################

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="$PROJECT_DIR/install"

# Import common logging functions
source "$INSTALL_DIR/common.sh"
export ROOT_HINT_SCRIPT="scripts/start-service.sh"

# Require root
require_root

SERVICE_NAME="wi-lab.service"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

echo ""
log_header "Wi-Lab Service Start"
echo ""

# Check service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    log_error "Service file not found at $SERVICE_FILE"
    log_info "Run: sudo bash install.sh"
    exit 1
fi

# Start the service
log_info "Starting service..."
systemctl start $SERVICE_NAME
log_success "Service started"

# Brief wait for service to stabilize
sleep 1

# Check if service is running
if systemctl is-active --quiet $SERVICE_NAME; then
    log_success "Service is running"
else
    log_error "Service did not start properly"
    systemctl status $SERVICE_NAME
    exit 1
fi

echo ""

# Display status
log_info "Checking service status..."
systemctl status $SERVICE_NAME --no-pager | head -n 10

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Extract gateway IP and API port for final summary display
GATEWAY_IP=$(get_gateway_ip)
API_PORT=$(get_api_port)

BASE_URL="http://${GATEWAY_IP}:${API_PORT}"

echo -e "${CYAN}📱 FRONTEND:${NC}"
echo "   Webpage:        ${GREEN}${BASE_URL}/${NC}"
echo ""
echo -e "${CYAN}🔌 API ENDPOINTS:${NC}"
echo "   Health Check:   ${GREEN}${BASE_URL}/api/v1/health${NC}"
echo "   Status:         ${GREEN}${BASE_URL}/api/v1/status${NC}"
echo ""
echo -e "${CYAN}📖 DOCUMENTATION:${NC}"
echo "   Swagger UI:     ${GREEN}${BASE_URL}/docs${NC}"
echo "   ReDoc:          ${GREEN}${BASE_URL}/redoc${NC}"
echo ""
