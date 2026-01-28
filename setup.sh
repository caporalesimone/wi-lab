#!/bin/bash

################################################################################
# Wi-Lab Setup Orchestrator Script
# 
# This script orchestrates the complete Wi-Lab installation by executing
# individual setup stages in sequence:
# 1. Preconditions (OS check, Docker check)
# 2. Preflight (dependency check and install)
# 3. Python venv setup
# 4. Systemd configuration
# 5. Autostart enablement
# 6. Frontend deployment
# 7. Verification
# 8. Final tests
#
# Usage: sudo bash setup.sh
################################################################################

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_DIR="$SCRIPT_DIR/setup"

# Import common logging functions
source "$SETUP_DIR/common.sh"

################################################################################
# Setup execution
################################################################################

log_info "Wi-Lab Setup - Starting..."
echo ""

# Define setup stages in execution order
STAGES=(
    "01-preconditions.sh"
    "02-preflight.sh"
    "03-venv.sh"
    "04-systemd.sh"
    "05-enable.sh"
    "07-deploy-frontend.sh"
    "06-verify.sh"
    "99-final-test.sh"
)

# Execute each stage
for stage in "${STAGES[@]}"; do
    STAGE_PATH="$SETUP_DIR/$stage"
    
    if [ ! -f "$STAGE_PATH" ]; then
        log_error "Stage script not found: $STAGE_PATH"
        exit 1
    fi
    
    log_info "Running: $stage"
    bash "$STAGE_PATH"
    echo ""
done

log_success "All setup stages completed! ✅"
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
