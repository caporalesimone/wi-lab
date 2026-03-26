#!/bin/bash

################################################################################
# Stage 0: Preconditions (OS check, Docker check, tools, config)
# Stage 1-5: Installation stages (venv, systemd, frontend, etc.)
# Stage 99: Final tests
#
# Usage: sudo bash install.sh
################################################################################

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR/install"

# Import common logging functions
source "$INSTALL_DIR/common.sh"
export ROOT_HINT_SCRIPT="install.sh"

# Initialize shared setup state for all stages.
install_common_vars
export WILAB_SETUP_STATE_FILE
state_init
state_set INSTALL_RUN_STARTED "1"
state_set INSTALL_RUN_STARTED_AT "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

################################################################################
# Installation execution
################################################################################

log_info "Wi-Lab Installation - Starting..."
log_info "Setup state file: $WILAB_SETUP_STATE_FILE"
echo ""

################################################################################
# Step 1: Discover and run precondition stages
################################################################################

# Dynamically discover precondition stages
# Find all stage scripts matching pattern [0-9][0-9]-*.sh and sort numerically
mapfile -t PRECOND_STAGES < <(find "$INSTALL_DIR/01-preconditions" -maxdepth 1 -type f -name '[0-9][0-9]-*.sh' | sort -V)

log_header "Precondition Checks"
echo ""

# Execute each precondition stage
for STAGE_PATH in "${PRECOND_STAGES[@]}"; do
    stage=$(basename "$STAGE_PATH")
    log_info "Running: $stage"
    bash "$STAGE_PATH"
    echo ""
done

log_success "All precondition checks passed ✅"
echo ""

################################################################################
# Step 2: Discover installation stages
################################################################################

# Dynamically discover installation stages
# Find all stage scripts matching pattern [0-9][0-9]-*.sh and sort numerically
# Exclude common.sh (library file)
mapfile -t STAGES < <(find "$INSTALL_DIR/02-install-stages" -maxdepth 1 -type f -name '[0-9][0-9]-*.sh' | sort -V)

################################################################################
# Step 3: Confirmation prompt
################################################################################
echo ""
echo "Installation Preview:"
echo ""
echo "After confirming, the installation will:"
echo ""
echo "  1. Check system dependencies"
echo "  2. Create Python virtual environment at /opt/wilab-venv"
echo "  3. Configure systemd service for autostart"
echo "  4. Deploy frontend application"
echo "  5. Run verification tests"
echo ""
echo "Configuration file: $WILAB_DIR/config.yaml"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -n "Proceed with installation? (y/N) "
read -r REPLY
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_warning "Installation cancelled"
    exit 0
fi

echo ""
log_info "Installation - Starting..."
echo ""

################################################################################
# Execute stages
################################################################################

log_header "Installation Stages"
echo ""

# Execute each stage in order
for STAGE_PATH in "${STAGES[@]}"; do
    stage=$(basename "$STAGE_PATH")
    
    log_info "Running: $stage"
    bash "$STAGE_PATH"
    echo ""
done

log_success "All installation stages completed! ✅"
echo ""

################################################################################
# Step 4: Discover and run test stages
################################################################################

# Dynamically discover test stages
mapfile -t TEST_STAGES < <(find "$INSTALL_DIR/03-tests" -maxdepth 1 -type f -name '[0-9][0-9]-*.sh' | sort -V)

if [ ${#TEST_STAGES[@]} -gt 0 ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    log_header "Test Stages"
    echo ""
    
    for TEST_STAGE_PATH in "${TEST_STAGES[@]}"; do
        stage=$(basename "$TEST_STAGE_PATH")
        
        log_info "Running: $stage"
        bash "$TEST_STAGE_PATH"
        echo ""
    done
    
    log_success "All test stages completed! ✅"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

################################################################################
# FINAL SUMMARY
################################################################################

# Extract gateway IP and API port for final summary display
GATEWAY_IP=$(get_gateway_ip)
API_PORT=$(get_api_port)

BASE_URL="http://${GATEWAY_IP}:${API_PORT}"

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

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log_info "Next steps:"
echo ""
echo "1. REBOOT TO TEST AUTOSTART:"
echo "   sudo reboot"
echo "   # After reboot, the service will automatically start"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log_success "Wi-Lab is ready! 🚀"
echo ""
