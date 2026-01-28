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

# Dynamically discover and execute setup stages
# Find all setup scripts matching pattern [0-9][0-9]-*.sh and sort numerically
# Exclude common.sh (library file)
mapfile -t STAGES < <(find "$SETUP_DIR" -maxdepth 1 -type f -name '[0-9][0-9]-*.sh' | sort -V)

if [ ${#STAGES[@]} -eq 0 ]; then
    log_error "No setup stages found in $SETUP_DIR"
    exit 1
fi

# Execute each stage in order
for STAGE_PATH in "${STAGES[@]}"; do
    stage=$(basename "$STAGE_PATH")
    
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
