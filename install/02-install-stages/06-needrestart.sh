#!/bin/bash
# Never let an unattended upgrade restart Wi-Lab: needrestart would stop every
# active network. GET /status (restart_required) and the web UI's red bar tell
# the operator, who restarts Wi-Lab when no network is in use.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common.sh"
install_common_vars

NEEDRESTART_CONF="/etc/needrestart/conf.d/wilab.conf"

if [ ! -d /etc/needrestart ]; then
    state_set INSTALL_NEEDRESTART_EXCLUDED "0"
    log_info "needrestart is not installed: nothing restarts Wi-Lab after an upgrade"
    exit 0
fi

mkdir -p /etc/needrestart/conf.d
cat > "$NEEDRESTART_CONF" <<'CONF'
# Written by the Wi-Lab installer: an upgrade never restarts wi-lab.service,
# since a restart stops every active network. Wi-Lab reports the pending
# restart in GET /status (restart_required) and in the web UI; restart it with
# `systemctl restart wi-lab` when no network is in use. Removed by uninstall.sh.
$nrconf{override_rc}{qr(^wi-lab\.service$)} = 0;
CONF
chmod 644 "$NEEDRESTART_CONF"
state_set INSTALL_NEEDRESTART_EXCLUDED "1"
log_success "wi-lab.service excluded from needrestart ($NEEDRESTART_CONF)"
