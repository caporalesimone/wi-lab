#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

WILAB_DIR="${WILAB_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV_PATH="${VENV_PATH:-/opt/wilab-venv}"

SERVICE_TEMPLATE="$SCRIPT_DIR/systemd/wi-lab.service.template"
SERVICE_TARGET="/etc/systemd/system/wi-lab.service"

log_info "Stage 04: Configuring systemd service..."

if [ ! -f "$SERVICE_TEMPLATE" ]; then
    log_error "Service template not found at $SERVICE_TEMPLATE"
    exit 1
fi

tmp_service=$(mktemp)
cp "$SERVICE_TEMPLATE" "$tmp_service"

sed -i "s|WILAB_DIR|${WILAB_DIR}|g" "$tmp_service"
sed -i "s|VENV_PATH|${VENV_PATH}|g" "$tmp_service"

log_info "Copying service file to $SERVICE_TARGET..."
cp "$tmp_service" "$SERVICE_TARGET"
rm -f "$tmp_service"

log_success "Service file configured"
log_info "  Installation: $WILAB_DIR"
log_info "  Virtual env: $VENV_PATH"
log_info "  Config: $WILAB_DIR/config.yaml"
