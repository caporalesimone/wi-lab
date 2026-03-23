#!/usr/bin/env bash
set -euo pipefail

sudo systemctl stop wi-lab.service
echo "Edit config.yaml and set non-conflicting dhcp_base_network."
echo "Then run: sudo systemctl restart wi-lab.service"
ip addr show | grep "inet " | head -1 || true
grep dhcp_base_network config.yaml || true
