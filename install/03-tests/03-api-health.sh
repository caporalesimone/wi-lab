#!/bin/bash

################################################################################
# Test Stage 03: API answers
#
# Wi-Lab has no health endpoint: GET /api/v2/status with the token of
# config.yaml must answer 200 with a "status" field. (/health is served by the
# frontend as an HTML page and proves nothing.)
#
# Usage: bash install/03-tests/03-api-health.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

API_PORT=$(get_api_port)
BASE_URL="http://localhost:${API_PORT}"
STATUS_URL="${BASE_URL}/api/v2/status"
state_set TEST_API_PORT "$API_PORT"
state_set TEST_BASE_URL "$BASE_URL"

# The venv has PyYAML; the system python may not.
TOKEN=$("$VENV_PATH/bin/python" -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["auth_token"])' \
    "$WILAB_DIR/config.yaml" 2>/dev/null)
if [ -z "$TOKEN" ]; then
    state_set TEST_HEALTH_OK "0"
    log_error "Cannot read auth_token from $WILAB_DIR/config.yaml"
    exit 1
fi

log_info "Testing $STATUS_URL ..."

# The service can take a few seconds to start every component.
MAX_RETRIES=20
RETRY_DELAY=3
RESPONSE=$(mktemp)
trap 'rm -f "$RESPONSE"' EXIT
HTTP_CODE=""
for ATTEMPT in $(seq 1 $MAX_RETRIES); do
    HTTP_CODE=$(curl -s -o "$RESPONSE" -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$STATUS_URL")
    if [ "$HTTP_CODE" = "200" ] && grep -q '"status"' "$RESPONSE"; then
        state_set TEST_HEALTH_OK "1"
        log_success "API is answering (attempt $ATTEMPT/$MAX_RETRIES): $(head -c 120 "$RESPONSE")"
        state_set TEST_STAGE_03_DONE "1"
        exit 0
    fi
    log_info "Attempt $ATTEMPT/$MAX_RETRIES: HTTP ${HTTP_CODE:-none} (waiting ${RETRY_DELAY}s)"
    sleep $RETRY_DELAY
done

state_set TEST_HEALTH_OK "0"
state_set TEST_HEALTH_LAST_HTTP_CODE "$HTTP_CODE"
log_error "API not answering after $MAX_RETRIES attempts (~$((MAX_RETRIES * RETRY_DELAY))s): last HTTP ${HTTP_CODE:-none}"
log_error "Check the service log: journalctl -u wi-lab -n 50"
exit 1
