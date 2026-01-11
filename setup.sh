#!/bin/bash

################################################################################
# Wi-Lab Setup Script
# 
# This script automates the complete Wi-Lab installation:
# 1. Detects installation directory
# 2. Creates Python virtual environment in network namespace
# 3. Installs Python dependencies
# 4. Configures systemd services with correct paths
# 5. Enables autostart
#
# Usage: sudo bash setup.sh
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
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

# Dependency checker and installer
REQUIRED_CMDS=(
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

    # Detect if python3 has ensurepip/venv available
    local need_ensurepip=0
    if ! python3 - <<'PY' 2>/dev/null
import ensurepip
PY
    then
        need_ensurepip=1
    fi

    # Ensure python venv/pip packages are requested if ensurepip is missing
    if [ $need_ensurepip -eq 1 ]; then
        pkg_set[python3-venv]=1
        pkg_set[python3-pip]=1
        # Add version-specific venv package if available on Debian/Ubuntu (e.g., python3.13-venv)
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

    # Build unique package list
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

        # Filter packages that actually exist in apt cache to avoid failures (e.g., python3-distutils on newer Ubuntu)
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

        # Re-check after install
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

################################################################################
# PRE-FLIGHT CHECKS
################################################################################

log_info "Wi-Lab Setup - Starting..."
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use: sudo bash setup.sh)"
    exit 1
fi

log_success "Running as root"

# Validate required system packages/commands
check_dependencies

# Detect Wi-Lab installation directory
WILAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd)"
log_info "Installation directory: $WILAB_DIR"

# Verify required files
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

# Check WiFi interface
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

echo ""

################################################################################
# STEP 1: Setup Python Virtual Environment
################################################################################

log_info "Step 1/3: Setting up Python virtual environment..."

VENV_PATH="/opt/wilab-venv"

if [ -d "$VENV_PATH" ]; then
    log_warning "Virtual environment already exists at $VENV_PATH"
    read -p "Recreate it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Removing old venv..."
        sudo rm -rf "$VENV_PATH"
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

echo ""

################################################################################
# STEP 2: Configure Systemd Services
################################################################################

log_info "Step 2/3: Configuring systemd services..."

# Create temporary file
WILAB_SERVICE=$(mktemp)

# Generate wilab.service
cat > "$WILAB_SERVICE" << 'EOFWS'
[Unit]
Description=Wi-Lab WiFi Access Point Manager
Documentation=https://github.com/your-org/wi-lab
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=WILAB_DIR
ExecStart=VENV_PATH/bin/python WILAB_DIR/main.py
Restart=always
RestartSec=10s
TimeoutStartSec=60s
TimeoutStopSec=30s

Environment="CONFIG_PATH=WILAB_DIR/config.yaml"
StandardOutput=journal
StandardError=journal
SyslogIdentifier=wilab

[Install]
WantedBy=multi-user.target
EOFWS

# Replace placeholders with actual paths
sed -i "s|WILAB_DIR|${WILAB_DIR}|g" "$WILAB_SERVICE"
sed -i "s|VENV_PATH|${VENV_PATH}|g" "$WILAB_SERVICE"

# Copy to systemd
log_info "Copying service file to /etc/systemd/system/..."
sudo cp "$WILAB_SERVICE" /etc/systemd/system/wilab.service

# Clean temp file
rm -f "$WILAB_SERVICE"

log_success "Service files configured with paths:"
log_info "  Installation: $WILAB_DIR"
log_info "  Virtual env: $VENV_PATH"
log_info "  Config: $WILAB_DIR/config.yaml"

echo ""

################################################################################
# STEP 3: Enable Autostart
################################################################################

log_info "Step 3/3: Enabling autostart..."

# Reload systemd
log_info "Reloading systemd daemon..."
sudo systemctl daemon-reload
log_success "Systemd daemon reloaded"

# Enable services
log_info "Enabling service..."
sudo systemctl enable wilab.service
log_success "Service enabled for autostart"

echo ""

################################################################################
# VERIFICATION
################################################################################

log_info "Verifying installation..."
echo ""

# Check systemd service
log_info "Service file:"
if systemctl is-enabled wilab.service &>/dev/null; then
    STATUS="enabled"
else
    STATUS="disabled"
fi
echo "  wilab.service: $STATUS"

# Check venv
log_info "Virtual environment:"
if [ -d "$VENV_PATH" ]; then
    PYTHON_VER=$("$VENV_PATH/bin/python" --version)
    echo "  $VENV_PATH: $PYTHON_VER"
else
    echo "  $VENV_PATH: not found"
fi

# Check config
log_info "Configuration:"
TOKENS=$(grep "auth_token:" "$WILAB_DIR/config.yaml" | head -1)
echo "  config.yaml: found"
echo "    $TOKENS"

echo ""

################################################################################
# FINAL INSTRUCTIONS
################################################################################

log_success "Setup complete! ✅"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log_info "Next steps:"
echo ""
echo "1. TEST MANUALLY (optional):"
echo "   sudo systemctl start wilab.service"
echo ""
echo "2. VERIFY SERVICE:"
echo "   sudo systemctl status wilab.service"
echo "   sudo journalctl -u wilab.service -f"
echo ""
echo "3. TEST API:"
echo "   curl http://localhost:8080/api/v1/health"
echo ""
echo "4. CLEANUP (after testing):"
echo "   sudo systemctl stop wilab.service"
echo ""
echo "5. REBOOT TO TEST AUTOSTART:"
echo "   sudo reboot"
echo "   # After reboot:"
echo "   sudo systemctl status wilab.service"
echo "   curl http://localhost:8080/api/v1/health"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log_info "Installation directory: $WILAB_DIR"
log_info "Virtual environment: $VENV_PATH"
log_info "Config file: $WILAB_DIR/config.yaml"
log_info "Documentation: $WILAB_DIR/docs/"
echo ""
log_success "Wi-Lab is ready! 🚀"
