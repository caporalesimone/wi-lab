#!/bin/bash

################################################################################
# Wi-Lab Reload Drivers Script (Fable ARCH-11 D1)
#
# Reloads the kernel driver of the Wi-Fi adapters Wi-Lab manages, with the
# Python and configuration of the installed service. Fixes an adapter whose
# firmware hangs and makes hostapd crash at every start. The service must be
# stopped: reloading a driver resets every adapter it drives. A driver that also
# drives the host's own network (default route, upstream_interface) is refused.
#
# Usage: sudo bash scripts/reload-drivers.sh   (or: make reload-drivers)
################################################################################

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="$PROJECT_DIR/install"

source "$INSTALL_DIR/common.sh"
export ROOT_HINT_SCRIPT="scripts/reload-drivers.sh"
require_root

SERVICE_FILE="/etc/systemd/system/wi-lab.service"

# The installed service knows which Python and which configuration it runs with: use the same.
install_common_vars
PYTHON="$VENV_PATH/bin/python"
CONFIG="$PROJECT_DIR/config.yaml"
if [ -f "$SERVICE_FILE" ]; then
    unit_python="$(sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' "$SERVICE_FILE" | head -n 1)"
    unit_config="$(sed -n 's/^Environment="\{0,1\}CONFIG_PATH=\([^"]*\)"\{0,1\}$/\1/p' "$SERVICE_FILE" | head -n 1)"
    [ -n "$unit_python" ] && PYTHON="$unit_python"
    [ -n "$unit_config" ] && CONFIG="$unit_config"
fi

if [ ! -x "$PYTHON" ]; then
    log_error "Python of the installed virtual environment not found at $PYTHON"
    log_info "Run: sudo bash install.sh"
    exit 1
fi

echo ""
log_header "Wi-Lab Reload Drivers"
echo ""

cd "$PROJECT_DIR"
exec "$PYTHON" "$PROJECT_DIR/main.py" --reload-drivers --config "$CONFIG"
