#!/bin/bash

################################################################################
# Preconditions Stage 03: Configuration Files
# 
# Checks:
# - config.yaml exists
# - requirements.txt exists
# - main.py exists
#
# Usage: bash setup/01-preconditions/03-config.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
setup_common_vars

################################################################################
# Verify config file exists
################################################################################

if [ ! -f "$WILAB_DIR/config.yaml" ]; then
    log_error "config.yaml not found in $WILAB_DIR"
    exit 1
fi
log_success "config.yaml found"

################################################################################
# Verify requirements file exists
################################################################################

if [ ! -f "$WILAB_DIR/requirements.txt" ]; then
    log_error "requirements.txt not found in $WILAB_DIR"
    exit 1
fi
log_success "requirements.txt found"

################################################################################
# Verify main application file exists
################################################################################

if [ ! -f "$WILAB_DIR/main.py" ]; then
    log_error "main.py not found in $WILAB_DIR"
    exit 1
fi
log_success "main.py found"

log_success "Configuration files satisfied"
