#!/bin/bash

################################################################################
# Preconditions Stage 04: System Tools
# 
# Checks:
# - All required system commands are available
# - Ask user if missing tools should be installed
# - Install missing packages only with user confirmation
#
# Usage: bash install/01-preconditions/04-tools.sh
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"

declare -a REQUIRED_CMDS=(
    "python3"
    "ip"
    "iptables"
    "hostapd"
    "dnsmasq"
    "iw"
    "jq"
    "nmcli"
    "systemctl"
)

declare -A CMD_TO_PKGS=(
    [python3]="python3 python3-venv python3-pip"
    [ip]="iproute2"
    [iptables]="iptables"
    [hostapd]="hostapd"
    [dnsmasq]="dnsmasq"
    [iw]="iw"
    [jq]="jq"
    [nmcli]="network-manager"
)

################################################################################
# Check for missing tools
################################################################################

check_tools() {
    local missing=()
    local packages=()
    declare -A pkg_set=()

    # Check for ensurepip requirement
    local need_ensurepip=0
    if ! python3 - <<'PY' 2>/dev/null
import ensurepip
PY
    then
        need_ensurepip=1
    fi

    if [ $need_ensurepip -eq 1 ]; then
        pkg_set[python3-venv]=1
        pkg_set[python3-pip]=1
        PY_MINOR=$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)
        pkg_set["python${PY_MINOR}-venv"]=1
    fi

    # Check which commands are missing
    for cmd in "${REQUIRED_CMDS[@]}"; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            missing+=("$cmd")
            if [[ -n "${CMD_TO_PKGS[$cmd]}" ]]; then
                for pkg in ${CMD_TO_PKGS[$cmd]}; do
                    pkg_set[$pkg]=1
                done
            fi
        fi
    done

    # Convert pkg_set to array
    for pkg in "${!pkg_set[@]}"; do
        packages+=("$pkg")
    done

    echo "${missing[@]}"
    echo "${packages[@]}"
}

################################################################################
# Main execution
################################################################################

log_info "Checking for required system tools..."
echo ""

# Get missing tools and packages
mapfile -t tool_state <<< "$(check_tools)"
missing_tools="${tool_state[0]}"
missing_packages="${tool_state[1]}"

state_set TOOLS_MISSING_COMMANDS "$missing_tools"
state_set TOOLS_MISSING_PACKAGES "$missing_packages"

if [ -z "$missing_tools" ]; then
    state_set TOOLS_ALL_PRESENT "1"
    state_set TOOLS_POSTCHECK_OK "1"
    log_success "All required system commands are already installed"
    echo ""
    log_success "System tools requirements satisfied"
    exit 0
fi

state_set TOOLS_ALL_PRESENT "0"

if [ -z "$missing_packages" ]; then
    log_error "Missing commands detected but no packages were resolved"
    exit 1
fi

################################################################################
# Tools are missing - ask for user confirmation
################################################################################

echo "⚠️  Missing system commands:"
for cmd in $missing_tools; do
    echo "   - $cmd"
done
echo ""

echo "Will install the following packages:"
for pkg in $missing_packages; do
    echo "   - $pkg"
done
echo ""

# Ask for user confirmation
echo -n "Install missing packages? (y/N) "
read -r REPLY
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    state_set TOOLS_INSTALL_REQUESTED "0"
    log_error "Missing tools required but installation declined"
    exit 1
fi
state_set TOOLS_INSTALL_REQUESTED "1"

echo ""
log_info "Installing required packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y $missing_packages
state_set TOOLS_INSTALLED_PACKAGES "$missing_packages"
echo ""

################################################################################
# Verify all tools are now available
################################################################################

log_info "Verifying installation..."
still_missing=()
for cmd in $missing_tools; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        still_missing+=("$cmd")
    fi
done

state_set TOOLS_POSTCHECK_MISSING "${still_missing[*]}"

if [ ${#still_missing[@]} -ne 0 ]; then
    state_set TOOLS_POSTCHECK_OK "0"
    log_error "Some commands are still missing after install: ${still_missing[*]}"
    exit 1
fi

state_set TOOLS_POSTCHECK_OK "1"

log_success "All required system commands are now available"
echo ""
log_success "System tools requirements satisfied"
