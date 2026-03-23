#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--force" ]]; then
  echo "This script is destructive. Re-run with --force" >&2
  exit 1
fi

sudo systemctl stop wi-lab.service
sudo pkill -f hostapd || true
sudo pkill -f dnsmasq || true
sudo iptables -F FORWARD
sudo iptables -F INPUT
sudo iptables -t nat -F POSTROUTING
sudo sysctl -w net.ipv4.ip_forward=0
for iface in $(iw dev | grep Interface | awk '{print $2}'); do
    sudo ip link set "$iface" down
    sudo iw dev "$iface" set type managed
    sudo ip link set "$iface" up
done
