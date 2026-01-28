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

if curl -s -I "$HOMEPAGE_URL" 2>&1 | grep -q "200\|301\|302"; then
    log_success "Homepage is responding"
else
    log_warning "Homepage may not be available"
fi

log_success "Homepage test completed"
