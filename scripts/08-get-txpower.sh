#!/bin/bash
# Get current TX power information for a network

set -e

# Configuration
TOKEN="${AUTH_TOKEN:-secret-token-12345}"
HOST="${API_HOST:-localhost}"
PORT="${API_PORT:-8080}"

# Default values
NET_ID="${1:-ap-01}"

echo "=== Get TX Power Info ==="
echo ""
echo "Parameters:"
echo "  Net ID:           $NET_ID"
echo ""

echo "Fetching TX power info..."
RESP=$(curl -s -X GET \
  -H "Authorization: Bearer $TOKEN" \
  "http://$HOST:$PORT/api/v1/interface/$NET_ID/txpower")

if command -v jq >/dev/null 2>&1; then
  echo "$RESP" | jq .
else
  echo "$RESP"
fi

echo ""
echo "✓ Done"
