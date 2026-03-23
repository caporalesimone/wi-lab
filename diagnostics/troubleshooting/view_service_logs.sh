#!/usr/bin/env bash
set -euo pipefail

mode="${1:-tail}"
case "$mode" in
  follow)
    sudo journalctl -u wi-lab.service -f
    ;;
  boot)
    sudo journalctl -u wi-lab.service -b
    ;;
  hour)
    sudo journalctl -u wi-lab.service --since "1 hour ago"
    ;;
  errors)
    sudo journalctl -u wi-lab.service | grep -E "ERROR|CRITICAL|Traceback" || true
    ;;
  *)
    sudo journalctl -u wi-lab.service -n 100
    ;;
esac
