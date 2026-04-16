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

# Initialize common variables used across installation stages
install_common_vars() {
    WILAB_DIR="${WILAB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
    VENV_PATH="${VENV_PATH:-/opt/wilab-venv}"
    WILAB_SETUP_STATE_FILE="${WILAB_SETUP_STATE_FILE:-/tmp/wilab-setup-state.env}"
}

# Validate that a state key is a safe shell variable name.
state_validate_key() {
    local key="$1"
    [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]]
}

# Initialize the setup state file for the current installation run.
state_init() {
    install_common_vars

    local state_dir
    state_dir="$(dirname "$WILAB_SETUP_STATE_FILE")"

    mkdir -p "$state_dir"
    : > "$WILAB_SETUP_STATE_FILE"
    chmod 600 "$WILAB_SETUP_STATE_FILE" 2>/dev/null || true

    echo "# Wi-Lab setup state" >> "$WILAB_SETUP_STATE_FILE"
    echo "# Generated at $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$WILAB_SETUP_STATE_FILE"
}

# Upsert a key/value pair in the setup state file.
state_set() {
    install_common_vars

    local key="$1"
    local value="${2:-}"
    local escaped_value
    local tmp_file

    if ! state_validate_key "$key"; then
        log_error "Invalid state key: $key"
        return 1
    fi

    if [ ! -f "$WILAB_SETUP_STATE_FILE" ]; then
        state_init
    fi

    printf -v escaped_value "%q" "$value"
    tmp_file="${WILAB_SETUP_STATE_FILE}.tmp.$$"

    grep -v -E "^${key}=" "$WILAB_SETUP_STATE_FILE" > "$tmp_file" || true
    echo "${key}=${escaped_value}" >> "$tmp_file"
    mv "$tmp_file" "$WILAB_SETUP_STATE_FILE"
}

# Return success when the key exists in the setup state file.
state_has() {
    install_common_vars

    local key="$1"

    if ! state_validate_key "$key"; then
        return 1
    fi

    [ -f "$WILAB_SETUP_STATE_FILE" ] && grep -q -E "^${key}=" "$WILAB_SETUP_STATE_FILE"
}

# Read and print a state value for a key.
state_get() {
    install_common_vars

    local key="$1"
    local line
    local encoded

    if ! state_validate_key "$key"; then
        return 1
    fi

    if [ ! -f "$WILAB_SETUP_STATE_FILE" ]; then
        return 1
    fi

    line="$(grep -E "^${key}=" "$WILAB_SETUP_STATE_FILE" | tail -1)"
    if [ -z "$line" ]; then
        return 1
    fi

    encoded="${line#*=}"
    eval "printf '%s\n' ${encoded}"
}

# Ensure script is run as root
require_root() {
    if [[ $EUID -ne 0 ]]; then
        local script_name
        script_name="${ROOT_HINT_SCRIPT:-$(basename "$0")}"
        log_error "This script must be run as root (use: sudo bash ${script_name})"
        exit 1
    fi
}

# Extract local IP of the machine (used for URL display)
get_gateway_ip() {
    local ip=$(hostname -I | awk '{print $1}')
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
