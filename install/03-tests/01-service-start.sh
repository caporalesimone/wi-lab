#!/bin/bash

################################################################################
# Test Stage 01: Service Startup
# 
# Starts the wi-lab service and waits for initialization
#
# Usage: bash install/03-tests/01-service-start.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

require_root

log_info "Starting wi-lab service..."
if systemctl start wi-lab.service; then
    state_set TEST_SERVICE_START_OK "1"
    log_success "Service started"
else
    state_set TEST_SERVICE_START_OK "0"
    log_error "Failed to start service"
    exit 1
fi

log_info "Waiting for service to initialize..."
sleep 3

state_set TEST_STAGE_01_DONE "1"

log_success "Service startup test passed"
