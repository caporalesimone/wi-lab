#!/bin/bash

################################################################################
# Preconditions Stage 02: Docker Requirements
# 
# Checks:
# - Docker is installed
# - Docker daemon is running
# - User has Docker permissions
#
# Usage: bash setup/01-preconditions/02-docker.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

################################################################################
# Verify Docker is installed
################################################################################

if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Please install Docker to continue."
    exit 1
fi
log_success "Docker is installed"

################################################################################
# Verify Docker daemon is running
################################################################################

if ! docker ps &> /dev/null; then
    log_error "Docker daemon is not running or user does not have permission. Please start Docker and ensure your user is in the 'docker' group."
    exit 1
fi
log_success "Docker daemon is running and accessible"

log_success "Docker requirements satisfied"
