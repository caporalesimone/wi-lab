#!/bin/bash

################################################################################
# Preconditions Stage 01: System Requirements
# 
# Checks:
# - Root permissions
# - OS is Ubuntu 25 or newer
# - Required system packages are available
#
# Usage: bash setup/01-preconditions/01-system.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

################################################################################
# Check root permissions
################################################################################

require_root

################################################################################
# Check OS version
################################################################################

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    if [[ "${ID}" != "ubuntu" ]]; then
        log_error "Unsupported OS: ${ID:-unknown}. Ubuntu 25 or newer is required."
        exit 1
    fi
    VERSION_MAJOR=${VERSION_ID%%.*}
    if [[ -z "$VERSION_MAJOR" ]]; then
        log_error "Unable to detect Ubuntu version from VERSION_ID=${VERSION_ID:-unset}."
        exit 1
    fi
    if (( VERSION_MAJOR < 25 )); then
        log_error "Ubuntu 25 or newer is required (detected ${VERSION_ID})."
        exit 1
    fi
    log_success "Ubuntu version OK: ${VERSION_ID}"
else
    log_error "/etc/os-release not found; unable to verify OS version."
    exit 1
fi

################################################################################
# Verify apt-get is available
################################################################################

if ! command -v apt-get >/dev/null 2>&1; then
    log_error "apt-get is not available; system package management required."
    exit 1
fi
log_success "System package manager available (apt-get)"

log_success "System requirements satisfied"
