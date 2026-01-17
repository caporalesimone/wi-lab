#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

log_info "Stage 01/06: Preconditions..."

if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use: sudo bash setup.sh)"
    exit 1
fi

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
else
    log_error "/etc/os-release not found; unable to verify OS version."
    exit 1
fi

log_success "Preconditions satisfied"

echo ""
echo "This setup will start the wi-lab service when it finishes."
echo "Make sure config.yaml is already updated (SSID, interfaces, token)."
read -p "Proceed anyway? (y/N) " -r REPLY
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_error "Setup cancelled: update config.yaml before running setup."
    exit 1
fi
