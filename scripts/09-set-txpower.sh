#!/bin/bash
# Set TX power level for an active network

set -e

# Configuration
TOKEN="${AUTH_TOKEN:-secret-token-12345}"
HOST="${API_HOST:-localhost}"
PORT="${API_PORT:-8080}"

# Default values
NET_ID="${1:-ap-01}"
LEVEL="${2:-2}"

echo "=== Set TX Power Level ==="
echo ""
echo "Parameters:"
echo "  Net ID:           $NET_ID"
echo "  Power Level:      $LEVEL (1=low, 4=max)"
echo ""

echo "Setting TX power (will wait 3s to verify change)..."
RESP=$(curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"level\":$LEVEL}" \
  "http://$HOST:$PORT/api/v1/interface/$NET_ID/txpower")

if command -v jq >/dev/null 2>&1; then
  echo "$RESP" | jq .
  
  # Show warning if present
  WARNING=$(echo "$RESP" | jq -r '.warning // empty')
  if [ -n "$WARNING" ]; then
    echo ""
    echo "⚠️  Warning: $WARNING"
  fi
else
  echo "$RESP"
fi

echo ""
echo "✓ Done"
