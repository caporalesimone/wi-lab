#!/usr/bin/env bash
set -euo pipefail

which hostapd
which dnsmasq
which iptables
which iw
ls -la /opt/wilab-venv/bin/python
sudo systemctl is-enabled wi-lab.service
sudo systemctl is-active wi-lab.service
echo "Open Swagger UI: http://localhost:8080/docs"
