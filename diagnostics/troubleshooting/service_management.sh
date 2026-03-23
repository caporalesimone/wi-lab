#!/usr/bin/env bash
set -euo pipefail

action="${1:-status}"
case "$action" in
  start|stop|restart)
    sudo systemctl "$action" wi-lab.service
    ;;
  reload)
    sudo systemctl daemon-reload
    ;;
  status)
    sudo systemctl status wi-lab.service
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|reload|status}" >&2
    exit 1
    ;;
esac
