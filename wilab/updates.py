"""Security updates installed on the host that need a restart (shown by GET /status).

Wi-Lab is excluded from needrestart (installer, `/etc/needrestart/conf.d/wilab.conf`):
an unattended upgrade must never restart it and drop every network. So the service
tells the operator itself, and the operator restarts it when no network is in use:

- `service`: a shared library (or the Python binary) this process has loaded was
  replaced on disk by an update: the mapping shows `(deleted)` in
  `/proc/self/maps`, the same test needrestart makes. Until a
  `systemctl restart wi-lab` the old, unpatched code keeps running.
- `system`: an update asks for a reboot (`/run/reboot-required`, a new kernel for
  example); `/run/reboot-required.pkgs` names the packages.

Reading both is a few file reads, done by the health loop every 10 s.
"""

from __future__ import annotations

import os
from pathlib import Path

MAPS = Path("/proc/self/maps")
REBOOT_REQUIRED = Path("/run/reboot-required")
REBOOT_PACKAGES = Path("/run/reboot-required.pkgs")
_DELETED = " (deleted)"
# Mappings that are deleted by design, not by an update.
_NOT_FILES = ("/memfd:", "/dev/shm/", "/SYSV", "/dev/zero", "/tmp/", "/run/")


def replaced_libraries(maps: Path | None = None) -> list[str]:
    """Files this process maps that an update replaced (shared libraries, the interpreter)."""
    maps = MAPS if maps is None else maps
    try:
        lines = maps.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found: set[str] = set()
    for line in lines:
        if not line.endswith(_DELETED):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        path = parts[5][: -len(_DELETED)]
        name = os.path.basename(path)
        if path.startswith(_NOT_FILES) or not path.startswith("/"):
            continue
        if ".so" in name or name.startswith("python"):
            found.add(path)
    return sorted(found)


def reboot_packages(flag: Path | None = None, packages: Path | None = None) -> list[str] | None:
    """Packages that asked for a reboot; None when no reboot is required."""
    flag = REBOOT_REQUIRED if flag is None else flag
    packages = REBOOT_PACKAGES if packages is None else packages
    if not flag.exists():
        return None
    try:
        return sorted({p for p in packages.read_text(encoding="utf-8").split() if p})
    except OSError:
        return []


def check() -> dict:
    """The `updates` check of /monitoring: what needs a restart, and why."""
    libraries = replaced_libraries()
    reboot = reboot_packages()
    return {
        "service_restart_required": bool(libraries),
        "replaced_libraries": libraries,
        "system_reboot_required": reboot is not None,
        "reboot_packages": reboot or [],
    }
