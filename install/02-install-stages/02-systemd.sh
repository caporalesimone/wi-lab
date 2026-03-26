#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

SERVICE_TEMPLATE="$SCRIPT_DIR/../systemd/wi-lab.service.template"
SERVICE_TARGET="/etc/systemd/system/wi-lab.service"
state_set INSTALL_SYSTEMD_TEMPLATE "$SERVICE_TEMPLATE"
state_set INSTALL_SYSTEMD_TARGET "$SERVICE_TARGET"

if [ ! -f "$SERVICE_TEMPLATE" ]; then
    state_set INSTALL_SYSTEMD_TEMPLATE_PRESENT "0"
    log_error "Service template not found at $SERVICE_TEMPLATE"
    exit 1
fi
state_set INSTALL_SYSTEMD_TEMPLATE_PRESENT "1"

tmp_service=$(mktemp)
cp "$SERVICE_TEMPLATE" "$tmp_service"

sed -i "s|WILAB_DIR|${WILAB_DIR}|g" "$tmp_service"
sed -i "s|VENV_PATH|${VENV_PATH}|g" "$tmp_service"

log_info "Copying service file to $SERVICE_TARGET..."
cp "$tmp_service" "$SERVICE_TARGET"
rm -f "$tmp_service"
state_set INSTALL_SYSTEMD_SERVICE_CONFIGURED "1"
state_set INSTALL_STAGE_02_DONE "1"

log_success "Service file configured"
log_info "  Installation: $WILAB_DIR"
log_info "  Virtual env: $VENV_PATH"
log_info "  Config: $WILAB_DIR/config.yaml"
