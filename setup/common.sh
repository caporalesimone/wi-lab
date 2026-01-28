#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Initialize common variables used across stages
setup_common_vars() {
    WILAB_DIR="${WILAB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
    VENV_PATH="${VENV_PATH:-/opt/wilab-venv}"
}

# Ensure script is run as root
require_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use: sudo bash setup.sh)"
        exit 1
    fi
}

# Extract gateway IP (used for URL display)
get_gateway_ip() {
    local ip=$(ip route | grep default | awk '{print $3}' | head -1)
    echo "${ip:-localhost}"
}

# Extract API port from config (fallback to 8080)
get_api_port() {
    if [ -f "config.yaml" ]; then
        grep "api_port:" config.yaml | sed 's/.*api_port:\s*//g' | head -1
    else
        echo "8080"
    fi
}

# Display a formatted header
log_header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}$1${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}
