"""Where Wi-Lab keeps its runtime files (STAB-2).

systemd creates the private directory (`RuntimeDirectory=wilab`, mode 0700) and
exports it as RUNTIME_DIRECTORY. Not /tmp: tmpfiles cleans files untouched for
days there (dnsmasq's PID file of a long-running network), and a fixed name in a
world-writable directory lets a local user prepare it for root to write into.
"""

import os

RUNTIME_DIR = os.environ.get("RUNTIME_DIRECTORY", "/run/wilab").split(":")[0]
HOSTAPD_RUNTIME_DIR = os.path.join(RUNTIME_DIR, "hostapd")
DNSMASQ_RUNTIME_DIR = os.path.join(RUNTIME_DIR, "dnsmasq")
# Used before 4.1.0: startup still stops orphans pointing there and removes them.
LEGACY_RUNTIME_DIRS = ("/tmp/wilab-hostapd", "/tmp/wilab-dnsmasq")


def make_private_dir(path: str) -> None:
    """Create *path* and its parent readable by root only (outside systemd too)."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    os.makedirs(path, mode=0o700, exist_ok=True)
