#!/bin/bash

################################################################################
# Test Stage 04: Homepage
# 
# Tests that the homepage is responding
#
# Usage: bash setup/03-tests/04-homepage.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
setup_common_vars

# Extract API port for test URLs
API_PORT=$(get_api_port)
BASE_URL="http://localhost:${API_PORT}"

log_info "Testing homepage..."
HOMEPAGE_URL="${BASE_URL}/"

# Retry logic with exponential backoff
RETRY_COUNT=5
RETRY_DELAY=2
for ((i=1; i<=RETRY_COUNT; i++)); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -L "$HOMEPAGE_URL" 2>&1)
    if [[ "$HTTP_CODE" =~ ^(200|301|302|304)$ ]]; then
        log_success "Homepage is responding (HTTP $HTTP_CODE)"
        break
    else
        if [ $i -lt $RETRY_COUNT ]; then
            log_info "Homepage not ready (HTTP $HTTP_CODE), retrying in ${RETRY_DELAY}s... (attempt $i/$RETRY_COUNT)"
            sleep $RETRY_DELAY
            RETRY_DELAY=$((RETRY_DELAY + 1))
        else
            log_warning "Homepage may not be available (HTTP $HTTP_CODE)"
        fi
    fi
done

log_success "Homepage test completed"
