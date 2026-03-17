#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
setup_common_vars

log_info "Service file:"
if systemctl is-enabled wi-lab.service &>/dev/null; then
    STATUS="enabled"
else
    STATUS="disabled"
fi
echo "  wi-lab.service: $STATUS"

log_info "Virtual environment:"
if [ -d "$VENV_PATH" ]; then
    PYTHON_VER=$("$VENV_PATH/bin/python" --version)
    echo "  $VENV_PATH: $PYTHON_VER"
else
    echo "  $VENV_PATH: not found"
fi

log_info "Configuration:"
TOKENS=$(grep "auth_token:" "$WILAB_DIR/config.yaml" | head -1)
echo "  config.yaml: found"
echo "    $TOKENS"

log_success "Verification completed"
