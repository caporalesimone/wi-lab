#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/setup/common.sh"

if [ -f "$COMMON_SH" ]; then
    # shellcheck source=/dev/null
    source "$COMMON_SH"
else
    log_info() { echo "[INFO] $1"; }
    log_success() { echo "[OK] $1"; }
    log_warning() { echo "[WARN] $1"; }
    log_error() { echo "[ERR] $1"; }
fi

export WILAB_DIR="${WILAB_DIR:-$SCRIPT_DIR}"
export VENV_PATH="${VENV_PATH:-/opt/wilab-venv}"
SERVICE_FILE="/etc/systemd/system/wi-lab.service"

log_info "Wi-Lab Uninstall - Starting..."

if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use: sudo bash uninstall.sh)"
    exit 1
fi

if command -v systemctl >/dev/null 2>&1; then
    log_info "Stopping service if running..."
    systemctl stop wi-lab.service 2>/dev/null || log_info "Service not running"

    log_info "Disabling service if enabled..."
    systemctl disable wi-lab.service 2>/dev/null || log_info "Service not enabled"

    if [ -f "$SERVICE_FILE" ]; then
        log_info "Removing systemd unit at $SERVICE_FILE..."
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
        log_success "Systemd unit removed"
    else
        log_info "No systemd unit found at $SERVICE_FILE"
    fi
else
    log_warning "systemctl not available; skipping service stop/disable"
fi

if [ -d "$VENV_PATH" ]; then
    echo -n "Remove virtual environment at $VENV_PATH? (y/N) "
    read -r REPLY
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Removing virtual environment..."
        rm -rf "$VENV_PATH"
        log_success "Virtual environment removed"
    else
        log_info "Keeping virtual environment"
    fi
else
    log_info "Virtual environment not found at $VENV_PATH"
fi

log_success "Uninstall completed."
