#!/usr/bin/env bash
set -euo pipefail

iw dev wlx782051245264 info | grep "tx power" || true
echo "Verify requested/reported TX power from Swagger UI: http://localhost:8080/docs"
