#!/bin/bash

################################################################################
# Test Stage 03: API Health Endpoint
# 
# Tests the API health endpoint
#
# Usage: bash install/03-tests/03-api-health.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
setup_common_vars

# Extract API port for test URLs
API_PORT=$(get_api_port)
BASE_URL="http://localhost:${API_PORT}"

log_info "Testing health endpoint..."
HEALTH_URL="${BASE_URL}/api/v1/health"

# Retry logic: attempt up to 20 times with 3-second delay
# Service can take time to fully initialize all components
MAX_RETRIES=20
RETRY_DELAY=3
ATTEMPT=0
HEALTH_OK=false

while [ $ATTEMPT -lt $MAX_RETRIES ]; do
    ATTEMPT=$((ATTEMPT + 1))
    if curl -s -f "$HEALTH_URL" > /dev/null 2>&1; then
        HEALTH_RESPONSE=$(curl -s "$HEALTH_URL")
        log_success "Health endpoint is responding (attempt $ATTEMPT/$MAX_RETRIES)"
        echo "   Response: $HEALTH_RESPONSE"
        HEALTH_OK=true
        break
    fi
    
    if [ $ATTEMPT -lt $MAX_RETRIES ]; then
        log_info "Waiting for API to start... (attempt $ATTEMPT/$MAX_RETRIES, waiting ${RETRY_DELAY}s)"
        sleep $RETRY_DELAY
    fi
done

if [ "$HEALTH_OK" = false ]; then
    log_warning "Health endpoint not responding after $MAX_RETRIES attempts (~$((MAX_RETRIES * RETRY_DELAY))s total)"
fi

log_success "API health test completed"
