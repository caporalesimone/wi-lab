#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

log_info "Service file:"
if systemctl is-enabled wi-lab.service &>/dev/null; then
    STATUS="enabled"
    state_set INSTALL_VERIFY_SERVICE_ENABLED "1"
else
    STATUS="disabled"
    state_set INSTALL_VERIFY_SERVICE_ENABLED "0"
fi
echo "  wi-lab.service: $STATUS"

log_info "Virtual environment:"
if [ -d "$VENV_PATH" ]; then
    PYTHON_VER=$("$VENV_PATH/bin/python" --version)
    state_set INSTALL_VERIFY_VENV_PRESENT "1"
    state_set INSTALL_VERIFY_PYTHON_VERSION "$PYTHON_VER"
    echo "  $VENV_PATH: $PYTHON_VER"
else
    state_set INSTALL_VERIFY_VENV_PRESENT "0"
    echo "  $VENV_PATH: not found"
fi

log_info "Configuration:"
TOKENS=$(grep "auth_token:" "$WILAB_DIR/config.yaml" | head -1)
if [ -n "$TOKENS" ]; then
    state_set INSTALL_VERIFY_CONFIG_PRESENT "1"
else
    state_set INSTALL_VERIFY_CONFIG_PRESENT "0"
fi
echo "  config.yaml: found"
echo "    $TOKENS"

state_set INSTALL_STAGE_04_DONE "1"

log_success "Verification completed"
