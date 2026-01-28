#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

WILAB_DIR="${WILAB_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV_PATH="${VENV_PATH:-/opt/wilab-venv}"

log_info "Stage 03: Setting up Python virtual environment..."

if [ -d "$VENV_PATH" ]; then
    log_warning "Virtual environment already exists at $VENV_PATH"
    read -p "Recreate it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Removing old venv..."
        rm -rf "$VENV_PATH"
    else
        log_info "Skipping venv creation"
    fi
fi

if [ ! -d "$VENV_PATH" ]; then
    log_info "Creating venv at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
    log_success "Virtual environment created"

    log_info "Installing Python dependencies..."
    "$VENV_PATH/bin/pip" install --upgrade pip setuptools wheel
    "$VENV_PATH/bin/pip" install --no-cache-dir -r "$WILAB_DIR/requirements.txt"
    log_success "Dependencies installed"
else
    log_success "Virtual environment already exists"
fi

log_success "Python environment stage completed"
