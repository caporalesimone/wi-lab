#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

if [ -d "$VENV_PATH" ]; then
    state_set INSTALL_VENV_EXISTS_BEFORE "1"
    log_warning "Virtual environment already exists at $VENV_PATH"
    read -p "Recreate it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        state_set INSTALL_VENV_RECREATE_REQUESTED "1"
        log_info "Removing old venv..."
        rm -rf "$VENV_PATH"
    else
        state_set INSTALL_VENV_RECREATE_REQUESTED "0"
        log_info "Skipping venv creation"
    fi
else
    state_set INSTALL_VENV_EXISTS_BEFORE "0"
fi

if [ ! -d "$VENV_PATH" ]; then
    log_info "Creating venv at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
    state_set INSTALL_VENV_CREATED "1"
    log_success "Virtual environment created"

    log_info "Installing Python dependencies..."
    "$VENV_PATH/bin/pip" install --upgrade pip setuptools wheel
    "$VENV_PATH/bin/pip" install --no-cache-dir -r "$WILAB_DIR/requirements.txt"
    state_set INSTALL_PY_DEPS_INSTALLED "1"
    log_success "Dependencies installed"
else
    state_set INSTALL_VENV_CREATED "0"
    state_set INSTALL_PY_DEPS_INSTALLED "0"
    log_success "Virtual environment already exists"
fi

state_set INSTALL_STAGE_01_DONE "1"

log_success "Python environment stage completed"
