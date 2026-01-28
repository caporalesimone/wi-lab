#!/bin/bash

################################################################################
# Test Stage 05: Documentation Endpoints
# 
# Tests that all documentation endpoints are available:
# - Swagger UI
# - OpenAPI JSON schema
# - ReDoc
#
# Usage: bash setup/03-tests/05-docs.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

# Extract API port for test URLs
API_PORT=$(get_api_port)
BASE_URL="http://localhost:${API_PORT}"

log_info "Testing documentation endpoints..."
echo ""

# Test Swagger UI
SWAGGER_URL="${BASE_URL}/docs"
echo -n "  Swagger UI: "
if curl -s -I "$SWAGGER_URL" 2>&1 | grep -q "200"; then
    echo -e "${GREEN}✅ Available${NC}"
else
    echo -e "${YELLOW}⚠️  Not available${NC}"
fi

# Test OpenAPI schema
OPENAPI_URL="${BASE_URL}/openapi.json"
echo -n "  OpenAPI JSON: "
if curl -s -I "$OPENAPI_URL" 2>&1 | grep -q "200"; then
    echo -e "${GREEN}✅ Available${NC}"
else
    echo -e "${YELLOW}⚠️  Not available${NC}"
fi

# Test ReDoc
REDOC_URL="${BASE_URL}/redoc"
echo -n "  ReDoc: "
if curl -s -I "$REDOC_URL" 2>&1 | grep -q "200"; then
    echo -e "${GREEN}✅ Available${NC}"
else
    echo -e "${YELLOW}⚠️  Not available${NC}"
fi

echo ""
log_success "Documentation endpoints test completed"
