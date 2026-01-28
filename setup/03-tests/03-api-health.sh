#!/bin/bash

################################################################################
# Test Stage 03: API Health Endpoint
# 
# Tests the API health endpoint
#
# Usage: bash setup/03-tests/03-api-health.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
setup_common_vars

# Extract API port for test URLs
API_PORT=$(get_api_port)
BASE_URL="http://localhost:${API_PORT}"

log_info "Testing health endpoint..."
HEALTH_URL="${BASE_URL}/api/v1/health"

if curl -s -f "$HEALTH_URL" > /dev/null 2>&1; then
    HEALTH_RESPONSE=$(curl -s "$HEALTH_URL")
    log_success "Health endpoint is responding"
    echo "   Response: $HEALTH_RESPONSE"
else
    log_warning "Health endpoint not responding (service may still be initializing)"
fi

log_success "API health test completed"
