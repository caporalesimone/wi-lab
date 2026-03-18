#!/bin/bash

################################################################################
# Wi-Lab Service Restart Script
# 
# Stops Wi-Lab service, waits 10 seconds, then restarts.
# Useful for testing code changes during development.
#
# Usage: sudo bash restart-service.sh
################################################################################

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR/install"

# Import common logging functions
source "$INSTALL_DIR/common.sh"
export ROOT_HINT_SCRIPT="restart-service.sh"

# Require root
require_root

SERVICE_NAME="wi-lab.service"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"
WAIT_TIME=10

echo ""
log_header "Wi-Lab Service Restart"
echo ""

# Check service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    log_error "Service file not found at $SERVICE_FILE"
    log_info "Run: sudo bash install.sh"
    exit 1
fi

# ============================================================================
# STEP 1: Stop the service
# ============================================================================

log_info "Step 1: Stopping service..."
if systemctl is-active --quiet $SERVICE_NAME; then
    systemctl stop $SERVICE_NAME
    log_success "Service stopped"
else
    log_warning "Service was not running"
fi

echo ""

# ============================================================================
# STEP 2: Wait before restart
# ============================================================================

log_info "Step 2: Waiting $WAIT_TIME seconds before restart..."
echo ""

# Show countdown
for ((i = $WAIT_TIME; i > 0; i--)); do
    printf "\r  ⏱️  Restarting in %2d seconds..." "$i"
    sleep 1
done

echo ""
echo ""

# ============================================================================
# STEP 3: Start the service
# ============================================================================

log_info "Step 3: Starting service..."
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

# ============================================================================
# STEP 5: Display status
# ============================================================================

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

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

log_success "Wi-Lab service restarted successfully! 🚀"

echo ""
log_info "Tip: Test your changes:"
echo "  curl -H 'Authorization: Bearer secret-token-12345' \\
  $BASE_URL/api/v1/status"
echo ""

# Show logs if requested
if [ "$1" = "-f" ] || [ "$1" = "--follow" ]; then
    echo ""
    log_info "Following service logs (Ctrl+C to exit)..."
    echo ""
    journalctl -u $SERVICE_NAME -f --no-hostname -o short-iso
fi
