#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

WILAB_DIR="${WILAB_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV_PATH="${VENV_PATH:-/opt/wilab-venv}"

log_info "Stage 06/06: Verification..."

log_info "Service file:"
if systemctl is-enabled wi-lab.service &>/dev/null; then
    STATUS="enabled"
else
    STATUS="disabled"
fi
echo "  wi-lab.service: $STATUS"

log_info "Virtual environment:"
if [ -d "$VENV_PATH" ]; then
    PYTHON_VER=$("$VENV_PATH/bin/python" --version)
    echo "  $VENV_PATH: $PYTHON_VER"
else
    echo "  $VENV_PATH: not found"
fi

log_info "Configuration:"
TOKENS=$(grep "auth_token:" "$WILAB_DIR/config.yaml" | head -1)
echo "  config.yaml: found"
echo "    $TOKENS"

log_success "Verification completed"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log_info "Next steps:"
echo ""
echo "1. TEST MANUALLY (optional):"
echo "   systemctl start wi-lab.service"
echo ""
echo "2. VERIFY SERVICE:"
echo "   systemctl status wi-lab.service"
echo "   journalctl -u wi-lab.service -f"
echo ""
echo "3. TEST API:"
echo "   curl http://localhost:8080/api/v1/health"
echo ""
echo "4. CLEANUP (after testing):"
echo "   systemctl stop wi-lab.service"
echo ""
echo "5. REBOOT TO TEST AUTOSTART:"
echo "   reboot"
echo "   # After reboot:"
echo "   systemctl status wi-lab.service"
echo "   curl http://localhost:8080/api/v1/health"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log_info "Installation directory: $WILAB_DIR"
log_info "Virtual environment: $VENV_PATH"
log_info "Config file: $WILAB_DIR/config.yaml"
log_info "Documentation: $WILAB_DIR/docs/"

log_success "Wi-Lab is ready! 🚀"
