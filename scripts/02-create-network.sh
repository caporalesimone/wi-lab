#!/bin/bash
# Create a test WiFi network

set -e

# Configuration
TOKEN="${AUTH_TOKEN:-secret-token-12345}"
HOST="${API_HOST:-localhost}"
PORT="${API_PORT:-8080}"

# Default values (override with environment or parameters)
NET_ID="${1:-ap-01}"
SSID="${2:-TestNetwork}"
CHANNEL="${3:-5}"
PASSWORD="${4:-testpass123}"
ENCRYPTION="${5:-wpa2}"
BAND="${6:-2.4ghz}"
TX_POWER="${7:-4}"
TIMEOUT="${8:-3600}"
INTERNET_ENABLED="${9:-true}"

echo "=== Creating WiFi Network ==="
echo ""
echo "Parameters:"
echo "  Net ID:           $NET_ID"
echo "  SSID:             $SSID"
echo "  Channel:          $CHANNEL"
echo "  Encryption:       $ENCRYPTION"
echo "  Band:             $BAND"
echo "  TX Power Level:   $TX_POWER (1=low, 4=max)"
echo "  Timeout (sec):    $TIMEOUT"
echo "  Internet:         $INTERNET_ENABLED"
echo ""

# Create the network
echo "Sending request..."
echo "Command: curl -s -X POST -H 'Authorization: Bearer $TOKEN' -H 'Content-Type: application/json' -d '{\"ssid\":\"$SSID\",\"channel\":$CHANNEL,\"password\":\"$PASSWORD\",\"encryption\":\"$ENCRYPTION\",\"band\":\"$BAND\",\"tx_power_level\":$TX_POWER,\"timeout\":$TIMEOUT,\"internet_enabled\":$INTERNET_ENABLED}' 'http://$HOST:$PORT/api/v1/interface/$NET_ID/network'"
RESP=$(curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"ssid\":\"$SSID\",\"channel\":$CHANNEL,\"password\":\"$PASSWORD\",\"encryption\":\"$ENCRYPTION\",\"band\":\"$BAND\",\"tx_power_level\":$TX_POWER,\"timeout\":$TIMEOUT,\"internet_enabled\":$INTERNET_ENABLED}" \
  "http://$HOST:$PORT/api/v1/interface/$NET_ID/network")
if command -v jq >/dev/null 2>&1; then
  echo "$RESP" | jq . 2>/dev/null || echo "$RESP"
else
  echo "$RESP"
fi
