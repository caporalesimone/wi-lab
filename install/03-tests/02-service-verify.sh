#!/bin/bash

################################################################################
# Test Stage 02: Service Verification
# 
# Verifies that the wi-lab service is running
#
# Usage: bash install/03-tests/02-service-verify.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

require_root

log_info "Verifying service status..."
if systemctl is-active --quiet wi-lab.service; then
    state_set TEST_SERVICE_ACTIVE "1"
    log_success "Service is running"
else
    state_set TEST_SERVICE_ACTIVE "0"
    log_error "Service is not running"
    systemctl status wi-lab.service
    exit 1
fi

state_set TEST_STAGE_02_DONE "1"

log_success "Service verification test passed"
