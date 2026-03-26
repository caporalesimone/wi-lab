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
install_common_vars

# Extract API port for test URLs
API_PORT=$(get_api_port)
BASE_URL="http://localhost:${API_PORT}"
state_set TEST_API_PORT "$API_PORT"
state_set TEST_BASE_URL "$BASE_URL"

log_info "Testing health endpoint..."
HEALTH_URL="${BASE_URL}/api/v1/health"
log_info "Health endpoint URL: $HEALTH_URL"

# Retry logic: attempt up to 20 times with 3-second delay
# Service can take time to fully initialize all components
MAX_RETRIES=20
RETRY_DELAY=3
ATTEMPT=0
HEALTH_OK=false

while [ $ATTEMPT -lt $MAX_RETRIES ]; do
    ATTEMPT=$((ATTEMPT + 1))
    
    # Test with debug output to detect connection issues
    HTTP_CODE=$(curl -s -w "%{http_code}" -o /tmp/health_response.txt "$HEALTH_URL" 2>/tmp/health_error.txt)
    CURL_EXIT=$?
    
    if [ $CURL_EXIT -eq 0 ] && [ "$HTTP_CODE" = "200" ]; then
        HEALTH_RESPONSE=$(cat /tmp/health_response.txt)
        log_success "Health endpoint is responding (attempt $ATTEMPT/$MAX_RETRIES)"
        echo "   Response: $HEALTH_RESPONSE"
        HEALTH_OK=true
        break
    fi
    
    if [ $ATTEMPT -lt $MAX_RETRIES ]; then
        ERROR_MSG=$(cat /tmp/health_error.txt 2>/dev/null)
        if [ -n "$ERROR_MSG" ]; then
            log_info "Attempt $ATTEMPT/$MAX_RETRIES: Connection error: $ERROR_MSG (waiting ${RETRY_DELAY}s)"
        else
            log_info "Attempt $ATTEMPT/$MAX_RETRIES: HTTP $HTTP_CODE, curl exit: $CURL_EXIT (waiting ${RETRY_DELAY}s)"
        fi
        sleep $RETRY_DELAY
    fi
done

if [ "$HEALTH_OK" = false ]; then
    state_set TEST_HEALTH_OK "0"
    state_set TEST_HEALTH_LAST_HTTP_CODE "$HTTP_CODE"
    state_set TEST_HEALTH_LAST_CURL_EXIT "$CURL_EXIT"
    log_warning "Health endpoint not responding after $MAX_RETRIES attempts (~$((MAX_RETRIES * RETRY_DELAY))s total)"
    log_warning "Last response: HTTP $HTTP_CODE, curl exit: $CURL_EXIT"
else
    state_set TEST_HEALTH_OK "1"
    state_set TEST_HEALTH_LAST_HTTP_CODE "200"
    state_set TEST_HEALTH_LAST_CURL_EXIT "0"
fi

state_set TEST_STAGE_03_DONE "1"

log_success "API health test completed"
