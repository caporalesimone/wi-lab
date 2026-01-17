#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

log_info "Stage 05/06: Enabling autostart..."

log_info "Reloading systemd daemon..."
systemctl daemon-reload
log_success "Systemd daemon reloaded"

log_info "Enabling service..."
systemctl enable wi-lab.service
log_success "Service enabled for autostart"

log_success "Autostart stage completed"
