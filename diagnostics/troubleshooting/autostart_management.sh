#!/usr/bin/env bash
set -euo pipefail

action="${1:-status}"
case "$action" in
  enable|disable)
    sudo systemctl "$action" wi-lab.service
    ;;
  status)
    sudo systemctl is-enabled wi-lab.service
    ;;
  *)
    echo "Usage: $0 {enable|disable|status}" >&2
    exit 1
    ;;
esac
