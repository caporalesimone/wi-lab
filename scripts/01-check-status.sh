#!/bin/bash
# Check Wi-Lab API health and interfaces (raw curl outputs only)

set -e

TOKEN="${AUTH_TOKEN:-secret-token-12345}"
HOST="${API_HOST:-localhost}"
PORT="${API_PORT:-8080}"

echo "=== Wi-Lab Status Check ==="
echo ""

# 1. Check API health
echo "1. Checking API health..."
echo "   Command: curl -s http://$HOST:$PORT/api/v1/health"
RESP=$(curl -s http://$HOST:$PORT/api/v1/health || true)
if command -v jq >/dev/null 2>&1; then
	echo "$RESP" | jq . 2>/dev/null || echo "$RESP"
else
	echo "$RESP"
fi
echo ""

# 2. List interfaces
echo "2. Listing managed interfaces..."
echo "   Command: curl -s -H 'Authorization: Bearer $TOKEN' http://$HOST:$PORT/api/v1/interfaces"
RESP=$(curl -s -H "Authorization: Bearer $TOKEN" http://$HOST:$PORT/api/v1/interfaces || true)
if command -v jq >/dev/null 2>&1; then
	echo "$RESP" | jq . 2>/dev/null || echo "$RESP"
else
	echo "$RESP"
fi
echo ""

echo "✅ Status check complete"
