#!/bin/bash
# Disable internet access for a network

set -e

TOKEN="${AUTH_TOKEN:-secret-token-12345}"
HOST="${API_HOST:-localhost}"
PORT="${API_PORT:-8080}"

NET_ID="${1:-ap-01}"

echo "=== Disabling Internet: $NET_ID ==="
echo ""

echo "Command: curl -s -X POST -H 'Authorization: Bearer $TOKEN' 'http://$HOST:$PORT/api/v1/interface/$NET_ID/internet/disable'"
RESP=$(curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://$HOST:$PORT/api/v1/interface/$NET_ID/internet/disable")
if command -v jq >/dev/null 2>&1; then
  echo "$RESP" | jq . 2>/dev/null || echo "$RESP"
else
  echo "$RESP"
fi
