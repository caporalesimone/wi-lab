#!/bin/bash

################################################################################
# Preconditions Stage 03: Configuration Files
# 
# Checks:
# - config.yaml exists
# - requirements.txt exists
# - main.py exists
#
# Usage: bash install/01-preconditions/03-config.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars
state_set CONFIG_WILAB_DIR "$WILAB_DIR"

################################################################################
# Verify config file exists
################################################################################

if [ ! -f "$WILAB_DIR/config.yaml" ]; then
    state_set CONFIG_PRESENT "0"
    log_error "config.yaml not found in $WILAB_DIR"
    exit 1
fi
state_set CONFIG_PRESENT "1"
state_set CONFIG_PATH "$WILAB_DIR/config.yaml"
log_success "config.yaml found"

################################################################################
# Verify requirements file exists
################################################################################

if [ ! -f "$WILAB_DIR/requirements.txt" ]; then
    state_set CONFIG_REQUIREMENTS_PRESENT "0"
    log_error "requirements.txt not found in $WILAB_DIR"
    exit 1
fi
state_set CONFIG_REQUIREMENTS_PRESENT "1"
log_success "requirements.txt found"

################################################################################
# Verify main application file exists
################################################################################

if [ ! -f "$WILAB_DIR/main.py" ]; then
    state_set CONFIG_MAIN_PY_PRESENT "0"
    log_error "main.py not found in $WILAB_DIR"
    exit 1
fi
state_set CONFIG_MAIN_PY_PRESENT "1"
log_success "main.py found"

log_success "Configuration files satisfied"
