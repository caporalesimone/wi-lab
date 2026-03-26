#!/bin/bash

################################################################################
# Test Stage 05: Documentation Endpoints
# 
# Tests that all documentation endpoints are available:
# - Swagger UI
# - OpenAPI JSON schema
# - ReDoc
#
# Usage: bash install/03-tests/05-docs.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

# Extract API port for test URLs
API_PORT=$(get_api_port)
BASE_URL="http://localhost:${API_PORT}"
state_set TEST_API_PORT "$API_PORT"
state_set TEST_BASE_URL "$BASE_URL"

log_info "Testing documentation endpoints..."
echo ""

# Test Swagger UI
SWAGGER_URL="${BASE_URL}/docs"
echo -n "  Swagger UI: "
if curl -s -I "$SWAGGER_URL" 2>&1 | grep -q "200"; then
    state_set TEST_DOCS_SWAGGER_OK "1"
    echo -e "${GREEN}✅ Available${NC}"
else
    state_set TEST_DOCS_SWAGGER_OK "0"
    echo -e "${YELLOW}⚠️  Not available${NC}"
fi

# Test OpenAPI schema
OPENAPI_URL="${BASE_URL}/openapi.json"
echo -n "  OpenAPI JSON: "
if curl -s -I "$OPENAPI_URL" 2>&1 | grep -q "200"; then
    state_set TEST_DOCS_OPENAPI_OK "1"
    echo -e "${GREEN}✅ Available${NC}"
else
    state_set TEST_DOCS_OPENAPI_OK "0"
    echo -e "${YELLOW}⚠️  Not available${NC}"
fi

# Test ReDoc
REDOC_URL="${BASE_URL}/redoc"
echo -n "  ReDoc: "
if curl -s -I "$REDOC_URL" 2>&1 | grep -q "200"; then
    state_set TEST_DOCS_REDOC_OK "1"
    echo -e "${GREEN}✅ Available${NC}"
else
    state_set TEST_DOCS_REDOC_OK "0"
    echo -e "${YELLOW}⚠️  Not available${NC}"
fi

echo ""
state_set TEST_STAGE_05_DONE "1"
log_success "Documentation endpoints test completed"
