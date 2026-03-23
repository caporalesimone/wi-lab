#!/usr/bin/env bash
set -euo pipefail

echo "Check network status/clients from Swagger UI: http://localhost:8080/docs"
ps aux | grep "[h]ostapd" || true
ps aux | grep "[d]nsmasq" || true
sudo iptables -L FORWARD -n -v | head -20
ip addr show | grep "inet " || true
grep dhcp_base_network config.yaml || true
