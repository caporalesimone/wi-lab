#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

log_info "Reloading systemd daemon..."
systemctl daemon-reload
state_set INSTALL_SYSTEMD_DAEMON_RELOADED "1"
log_success "Systemd daemon reloaded"

log_info "Enabling service..."
systemctl enable wi-lab.service
state_set INSTALL_SERVICE_ENABLED "1"
state_set INSTALL_STAGE_03_DONE "1"
log_success "Service enabled for autostart"

log_success "Autostart stage completed"
