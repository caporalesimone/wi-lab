#!/usr/bin/env bash
set -euo pipefail

echo "=== Wi-Lab Health Check ==="
echo
echo "1. Service Status:"
sudo systemctl status wi-lab.service | grep "Active:" || true
echo
echo "2. Swagger UI reachable:"
echo "Open http://localhost:8080/docs"
echo
echo "3. Interface list available from Swagger UI"
echo
echo "4. WiFi Interface Status:"
iw dev | grep -E "Interface|type" || true
echo
echo "5. Port 8080 Listening:"
sudo ss -tlnp | grep :8080 | awk '{print "OK", $4}' || true
echo
echo "6. Recent Errors:"
sudo journalctl -u wi-lab.service -n 20 | grep -i "error" | wc -l
echo
echo "=== Check Complete ==="
