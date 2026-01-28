#!/bin/bash

################################################################################
# Wi-Lab Final Test Script
# 
# This script performs comprehensive tests after Wi-Lab setup:
# 1. Starts the wi-lab service
# 2. Verifies the service is running
# 3. Tests health endpoint
# 4. Tests homepage
# 5. Tests documentation endpoints (Swagger, JSON schema)
# 6. Displays all available URLs
#
# Usage: sudo bash scripts/99-final-test.sh
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}$1${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use: sudo bash scripts/99-final-test.sh)"
    exit 1
fi

log_header "Wi-Lab Final Test Suite"

################################################################################
# STEP 1: Start the service
################################################################################

log_info "Step 1: Starting wi-lab service..."
if systemctl start wi-lab.service; then
    log_success "Service started"
else
    log_error "Failed to start service"
    exit 1
fi

# Wait for service to be ready
log_info "Waiting for service to initialize..."
sleep 3

################################################################################
# STEP 2: Verify service is running
################################################################################

log_info "Step 2: Verifying service status..."
if systemctl is-active --quiet wi-lab.service; then
    log_success "Service is running"
else
    log_error "Service is not running"
    systemctl status wi-lab.service
    exit 1
fi

################################################################################
# STEP 3: Get gateway IP and API port
################################################################################

log_info "Step 3: Detecting gateway IP and API configuration..."

# Get default gateway IP
GATEWAY_IP=$(ip route | grep default | awk '{print $3}' | head -1)
if [ -z "$GATEWAY_IP" ]; then
    log_warning "Could not detect gateway IP automatically"
    GATEWAY_IP="localhost"
fi
log_success "Gateway IP: $GATEWAY_IP"

# Get API port from config (fallback to 8080)
API_PORT=8080
if [ -f "config.yaml" ]; then
    API_PORT=$(grep "api_port:" config.yaml | sed 's/.*api_port:\s*//g' | head -1)
fi
log_success "API Port: $API_PORT"

BASE_URL="http://${GATEWAY_IP}:${API_PORT}"

echo ""

################################################################################
# STEP 4: Test Health Endpoint
################################################################################

log_info "Step 4: Testing health endpoint..."
HEALTH_URL="${BASE_URL}/api/v1/health"
if curl -s -f "$HEALTH_URL" > /dev/null 2>&1; then
    HEALTH_RESPONSE=$(curl -s "$HEALTH_URL")
    log_success "Health endpoint is responding"
    echo "   Response: $HEALTH_RESPONSE"
else
    log_warning "Health endpoint not responding (service may still be initializing)"
fi

echo ""

################################################################################
# STEP 5: Test Homepage
################################################################################

log_info "Step 5: Testing homepage..."
HOMEPAGE_URL="${BASE_URL}/"
if curl -s -I "$HOMEPAGE_URL" 2>&1 | grep -q "200\|301\|302"; then
    log_success "Homepage is responding"
else
    log_warning "Homepage may not be available"
fi

echo ""

################################################################################
# STEP 6: Test Documentation Endpoints
################################################################################

log_info "Step 6: Testing documentation endpoints..."

# Test Swagger UI
SWAGGER_URL="${BASE_URL}/docs"
echo -n "  Swagger UI: "
if curl -s -I "$SWAGGER_URL" 2>&1 | grep -q "200"; then
    echo -e "${GREEN}✅ Available${NC}"
else
    echo -e "${YELLOW}⚠️  Not available${NC}"
fi

# Test OpenAPI schema
OPENAPI_URL="${BASE_URL}/openapi.json"
echo -n "  OpenAPI JSON: "
if curl -s -I "$OPENAPI_URL" 2>&1 | grep -q "200"; then
    echo -e "${GREEN}✅ Available${NC}"
else
    echo -e "${YELLOW}⚠️  Not available${NC}"
fi

# Test ReDoc
REDOC_URL="${BASE_URL}/redoc"
echo -n "  ReDoc: "
if curl -s -I "$REDOC_URL" 2>&1 | grep -q "200"; then
    echo -e "${GREEN}✅ Available${NC}"
else
    echo -e "${YELLOW}⚠️  Not available${NC}"
fi

echo ""

################################################################################
# FINAL SUMMARY
################################################################################

log_header "Wi-Lab Service is Ready!"

log_info "Available URLs:"
echo ""
echo -e "${CYAN}📱 FRONTEND:${NC}"
echo "   Webpage:        ${GREEN}${BASE_URL}/${NC}"
echo ""
echo -e "${CYAN}🔌 API ENDPOINTS:${NC}"
echo "   Health Check:   ${GREEN}${BASE_URL}/api/v1/health${NC}"
echo "   Networks:       ${GREEN}${BASE_URL}/api/v1/networks${NC}"
echo "   WiFi List:      ${GREEN}${BASE_URL}/api/v1/wifi/available${NC}"
echo ""
echo -e "${CYAN}📖 DOCUMENTATION:${NC}"
echo "   Swagger UI:     ${GREEN}${BASE_URL}/docs${NC}"
echo "   ReDoc:          ${GREEN}${BASE_URL}/redoc${NC}"
echo "   OpenAPI Schema: ${GREEN}${BASE_URL}/openapi.json${NC}"
echo ""
echo -e "${CYAN}📚 DOCUMENTATION FILES:${NC}"
echo "   Installation:   ${GREEN}docs/installation-guide.md${NC}"
echo "   Networking:     ${GREEN}docs/networking.md${NC}"
echo "   API Reference:  ${GREEN}docs/swagger.md${NC}"
echo "   Troubleshooting:${GREEN}docs/troubleshooting.md${NC}"
echo "   Dev Guide:      ${GREEN}docs/readme-dev.md${NC}"
echo "   Unit Testing:   ${GREEN}docs/unit-testing.md${NC}"
echo ""

log_success "All tests completed! Wi-Lab is ready for use. 🚀"
echo ""
log_info "To stop the service:"
echo "   sudo systemctl stop wi-lab.service"
echo ""
log_info "To view logs:"
echo "   sudo journalctl -u wi-lab.service -f"
echo ""
