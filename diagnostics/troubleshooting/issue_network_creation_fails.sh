#!/usr/bin/env bash
set -euo pipefail

sudo journalctl -u wi-lab.service -n 100
iw dev
iw list | grep -A 5 "Supported interface modes" | grep "AP" || true
nmcli dev || true
echo "Retry network creation from Swagger UI: http://localhost:8080/docs"
