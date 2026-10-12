#!/bin/bash

################################################################################
# Install Stage 02b: Configuration Validation
#
# Validates config.yaml before the service is ever enabled, so a misconfigured
# install fails HERE with a readable report instead of silently failing later
# and leaving the operator to dig it out of journalctl.
#
# Ordering (the orchestrator discovers stages with `find | sort -V`):
#   - AFTER  01-venv.sh    : the validator runs on the project's interpreter and
#                            needs pyyaml and pydantic, so it cannot live in
#                            01-preconditions/ where only file existence is checked.
#   - AFTER  02-systemd.sh : sorts after it ("02-s" < "02-v"); writing the unit
#                            file is harmless either way.
#   - BEFORE 03-enable.sh  : nothing must be enabled or started against a config
#                            that will not load.
#
# Hardware checks are included: unlike a developer laptop, the install target is
# the bench, and the adapters must actually be there.
#
# Usage: bash install/02-install-stages/02-validate-config.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

log_info "Validating configuration..."

if [ ! -x "$VENV_PATH/bin/python" ]; then
    state_set INSTALL_CONFIG_VALIDATED "0"
    log_error "Virtual environment not found at $VENV_PATH — run stage 01 first"
    exit 1
fi

set +e
"$VENV_PATH/bin/python" "$WILAB_DIR/main.py" \
    --config "$WILAB_DIR/config.yaml" \
    --validate-config \
    --check-hardware
VALIDATION_EXIT=$?
set -e

case "$VALIDATION_EXIT" in
    0)
        state_set INSTALL_CONFIG_VALIDATED "1"
        log_success "Configuration is valid"
        ;;
    2)
        state_set INSTALL_CONFIG_VALIDATED "0"
        log_error "config.yaml is missing, unreadable, or not valid YAML (see report above)"
        exit 1
        ;;
    *)
        state_set INSTALL_CONFIG_VALIDATED "0"
        log_error "Configuration is invalid — fix the problems listed above and re-run the installer"
        log_info "You can re-check at any time with:"
        log_info "  $VENV_PATH/bin/python $WILAB_DIR/main.py --validate-config"
        exit 1
        ;;
esac

state_set INSTALL_STAGE_02_VALIDATE_DONE "1"

log_success "Configuration validation stage completed"
