#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

WILAB_DIR="${WILAB_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV_PATH="${VENV_PATH:-/opt/wilab-venv}"

log_info "Stage 02/06: Pre-flight checks..."

declare -a REQUIRED_CMDS=(
    "python3"
    "ip"
    "iptables"
    "hostapd"
    "dnsmasq"
    "iw"
    "jq"
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
)

check_dependencies() {
    local missing=()
    local packages=()
    declare -A pkg_set=()

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

    for pkg in "${!pkg_set[@]}"; do
        packages+=("$pkg")
    done

    if [ ${#packages[@]} -ne 0 ]; then
        if [ ${#missing[@]} -ne 0 ]; then
            log_warning "Missing system commands: ${missing[*]}"
        fi

        if ! command -v apt-get >/dev/null 2>&1; then
            log_error "apt-get is not available; install required packages manually."
            exit 1
        fi

        local install_pkgs=()
        for pkg in "${packages[@]}"; do
            if apt-cache show "$pkg" >/dev/null 2>&1; then
                install_pkgs+=("$pkg")
            else
                log_warning "Skipping unavailable package: $pkg"
            fi
        done

        if [ ${#install_pkgs[@]} -eq 0 ]; then
            log_warning "No installable packages detected; continuing without apt-get"
        else
            log_info "Installing required packages: ${install_pkgs[*]}"
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -y
            apt-get install -y "${install_pkgs[@]}"
        fi

        local still_missing=()
        for cmd in "${missing[@]}"; do
            if ! command -v "$cmd" >/dev/null 2>&1; then
                still_missing+=("$cmd")
            fi
        done

        if [ ${#still_missing[@]} -ne 0 ]; then
            log_error "Some commands are still missing after install: ${still_missing[*]}"
            exit 1
        fi
    fi

    log_success "All required system commands are available"
}

check_dependencies

log_info "Installation directory: $WILAB_DIR"

if [ ! -f "$WILAB_DIR/config.yaml" ]; then
    log_error "config.yaml not found in $WILAB_DIR"
    exit 1
fi
log_success "config.yaml found"

if [ ! -f "$WILAB_DIR/requirements.txt" ]; then
    log_error "requirements.txt not found in $WILAB_DIR"
    exit 1
fi
log_success "requirements.txt found"

if [ ! -f "$WILAB_DIR/main.py" ]; then
    log_error "main.py not found in $WILAB_DIR"
    exit 1
fi
log_success "main.py found"

WIFI_IFACE=$(grep -E "^\s+interface:" "$WILAB_DIR/config.yaml" 2>/dev/null | head -1 | sed -E 's/.*interface:\s*"?([^"]+)"?.*/\1/' | xargs)
if [ -z "$WIFI_IFACE" ]; then
    log_error "No WiFi interface found in config.yaml"
    exit 1
fi
log_info "WiFi interface: $WIFI_IFACE"

if ! ip link show "$WIFI_IFACE" &>/dev/null; then
    log_warning "WiFi interface $WIFI_IFACE not found on host"
    log_info "  (This is OK if it's in a namespace already)"
fi

log_success "Pre-flight checks completed"
