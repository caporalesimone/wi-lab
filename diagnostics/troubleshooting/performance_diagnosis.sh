#!/usr/bin/env bash
set -euo pipefail

iw dev wlx782051245264 info
sudo iw dev wlx782051245264 scan | grep -E "SSID:|signal:" || true
echo "Check TX power from Swagger UI: http://localhost:8080/docs"
