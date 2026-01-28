#!/bin/bash

################################################################################
# Test Stage 02: Service Verification
# 
# Verifies that the wi-lab service is running
#
# Usage: bash setup/03-tests/02-service-verify.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
setup_common_vars

require_root

log_info "Verifying service status..."
if systemctl is-active --quiet wi-lab.service; then
    log_success "Service is running"
else
    log_error "Service is not running"
    systemctl status wi-lab.service
    exit 1
fi

log_success "Service verification test passed"
