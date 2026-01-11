#!/bin/bash
# Check Wi-Lab systemd service state (non-interactive)

set -e

SERVICE_NAME="${SERVICE_NAME:-wilab.service}"

echo "=== Wi-Lab Service Check (${SERVICE_NAME}) ==="

# Prefer without sudo; fallback to sudo -n (no prompt)
if systemctl is-active --quiet "$SERVICE_NAME" || sudo -n systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  echo "✅ Service running"
else
  STATE=$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo "unknown")
  echo "❌ Service not running (state: $STATE)"
fi
