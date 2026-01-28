#!/bin/bash
# Run complete test suite with summary

set -e

echo "================================"
echo "Wi-Lab Test Suite Runner"
echo "================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

cd "$(dirname "$0")" || exit 1

echo "Environment:"
echo "  Python: $(python3 --version)"
echo "  Working dir: $(pwd)"
echo ""

# Install dependencies if needed
if ! python3 -c "import pytest" 2>/dev/null; then
    echo "Installing pytest..."
    python3 -m pip install --break-system-packages -q pytest pytest-cov 2>/dev/null || true
fi

# Run tests
echo "Running test suite..."
echo ""

python3 -m pytest tests/ \
    --tb=short \
    -v \
    --color=yes \
    --durations=10 \
    2>&1 | tee test-report.txt

echo ""
echo "Test Results Summary:"
echo "======================"

# Extract summary
if grep -q "passed" test-report.txt; then
    PASSED=$(grep -oP '\d+(?= passed)' test-report.txt | tail -1)
    echo -e "${GREEN}✓ Tests passed: $PASSED${NC}"
fi

if grep -q "failed" test-report.txt; then
    FAILED=$(grep -oP '\d+(?= failed)' test-report.txt | tail -1)
    echo -e "${RED}✗ Tests failed: $FAILED${NC}"
fi

if grep -q "error" test-report.txt; then
    ERRORS=$(grep -oP '\d+(?= error)' test-report.txt | tail -1)
    echo -e "${RED}✗ Test errors: $ERRORS${NC}"
fi

if grep -q "skipped" test-report.txt; then
    SKIPPED=$(grep -oP '\d+(?= skipped)' test-report.txt | tail -1)
    echo -e "${YELLOW}⊘ Tests skipped: $SKIPPED${NC}"
fi

echo ""
echo "Report saved to: test-report.txt"
