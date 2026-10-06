#!/bin/bash

################################################################################
# Wi-Lab Reload Drivers Script
#
# Reloads the kernel driver of the WiFi adapters listed in config.yaml, with the
# virtual environment the installer created (the one the service runs with).
# Fixes an adapter whose firmware hangs and makes hostapd crash. The service must
# be stopped: reloading a driver resets every adapter that uses it.
#
# Usage: sudo bash scripts/reload-drivers.sh
################################################################################

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="$PROJECT_DIR/install"

# Import common logging functions
source "$INSTALL_DIR/common.sh"
export ROOT_HINT_SCRIPT="scripts/reload-drivers.sh"

# Require root
require_root

SERVICE_FILE="/etc/systemd/system/wi-lab.service"

# The installed service knows which Python and which configuration it runs with: use the same.
install_common_vars
PYTHON="$VENV_PATH/bin/python"
CONFIG="$PROJECT_DIR/config.yaml"
if [ -f "$SERVICE_FILE" ]; then
    unit_python="$(sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' "$SERVICE_FILE" | head -n 1)"
    unit_config="$(sed -n 's/^Environment="CONFIG_PATH=\(.*\)"$/\1/p' "$SERVICE_FILE" | head -n 1)"
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

exec "$PYTHON" "$PROJECT_DIR/main.py" --config "$CONFIG" --reload-drivers
