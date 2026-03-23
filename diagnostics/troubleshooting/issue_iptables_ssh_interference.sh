#!/usr/bin/env bash
set -euo pipefail

sudo iptables -L FORWARD -n -v
sudo iptables -t nat -L POSTROUTING -n -v
echo "If needed: stop service, flush FORWARD and POSTROUTING, then restart service."
