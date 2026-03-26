#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

FRONTEND_DIR="$WILAB_DIR/frontend"
DEPLOY_SCRIPT="$FRONTEND_DIR/deploy_frontend.sh"
state_set INSTALL_FRONTEND_DIR "$FRONTEND_DIR"
state_set INSTALL_FRONTEND_DEPLOY_SCRIPT "$DEPLOY_SCRIPT"

# Check if frontend directory exists
if [ ! -d "$FRONTEND_DIR" ]; then
    state_set INSTALL_FRONTEND_DIR_PRESENT "0"
    log_error "Frontend directory not found at $FRONTEND_DIR"
    exit 1
fi
state_set INSTALL_FRONTEND_DIR_PRESENT "1"

# Check if deploy script exists
if [ ! -f "$DEPLOY_SCRIPT" ]; then
    state_set INSTALL_FRONTEND_DEPLOY_SCRIPT_PRESENT "0"
    log_error "Deploy script not found at $DEPLOY_SCRIPT"
    exit 1
fi
state_set INSTALL_FRONTEND_DEPLOY_SCRIPT_PRESENT "1"

# Make sure the script is executable
chmod +x "$DEPLOY_SCRIPT"

# Run the frontend build script
log_info "Running frontend build (this may take a few minutes)..."
cd "$FRONTEND_DIR"
bash "$DEPLOY_SCRIPT"

# Verify build output exists
BUILD_OUTPUT="$FRONTEND_DIR/dist/wi-lab-frontend/browser"
if [ ! -d "$BUILD_OUTPUT" ]; then
    state_set INSTALL_FRONTEND_BUILD_OUTPUT_PRESENT "0"
    log_error "Build output not found at $BUILD_OUTPUT"
    exit 1
fi
state_set INSTALL_FRONTEND_BUILD_OUTPUT_PRESENT "1"
state_set INSTALL_FRONTEND_BUILD_OUTPUT "$BUILD_OUTPUT"
state_set INSTALL_STAGE_05_DONE "1"

log_success "Frontend built successfully"
log_info "Frontend files available at: $BUILD_OUTPUT"

echo ""
log_info "FastAPI will serve these files from: $BUILD_OUTPUT"
log_info "Access the frontend at: http://localhost:8080/"

log_success "Frontend deployment completed"
