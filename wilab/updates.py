"""Security updates installed on the host that need a restart (shown by GET /status).

Wi-Lab is excluded from needrestart (installer, `/etc/needrestart/conf.d/wilab.conf`):
an unattended upgrade must never restart it and drop every network. So the service
tells the operator itself, and the operator restarts it when no network is in use:

- `service`: a shared library (or the Python binary) this process has loaded was
  replaced on disk by an update: the mapping shows `(deleted)` in
  `/proc/self/maps`, the same test needrestart makes. Until a
  `systemctl restart wi-lab` the old, unpatched code keeps running.
- `system`: an update asks for a reboot. Three sources, so it works beyond Ubuntu:
  `/run/reboot-required` (Debian, Ubuntu; `/run/reboot-required.pkgs` names the
  packages), `/run/reboot-needed` (openSUSE's zypper), and on any distribution a
  kernel newer than the running one installed in `/lib/modules` with the same
  flavour, or the running kernel's modules removed (Arch replaces them in place).
  Wi-Lab requires Ubuntu (README); the last two keep the check honest elsewhere.

Reading both is a few file reads, done by the health loop every 10 s.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

MAPS = Path("/proc/self/maps")
REBOOT_REQUIRED = Path("/run/reboot-required")
REBOOT_PACKAGES = Path("/run/reboot-required.pkgs")
REBOOT_NEEDED = Path("/run/reboot-needed")          # openSUSE (zypper)
MODULES = Path("/lib/modules")
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


def _flavour(release: str) -> str:
    """`7.0.0-44-generic` -> `generic`: kernels are only compared within a flavour."""
    match = re.search(r"[-+]([A-Za-z][\w.+-]*)$", release)
    return match[1] if match else ""


def _version(release: str) -> tuple[int, ...]:
    """The numbers of a release without its flavour: `7.0.0-44-generic` -> (7, 0, 0, 44)."""
    flavour = _flavour(release)
    base = release[: -len(flavour) - 1] if flavour else release
    return tuple(int(n) for n in re.findall(r"\d+", base))


def newer_kernel(running: str | None = None, modules: Path | None = None) -> str | None:
    """The kernel a reboot would start instead of the running one; None when it is the newest.

    Generic (any distribution): the running kernel's modules were removed, or a
    newer kernel of the same flavour is installed next to it.
    """
    running = os.uname().release if running is None else running
    modules = MODULES if modules is None else modules
    try:
        installed = [d.name for d in modules.iterdir() if (d / "modules.dep").exists() or (d / "kernel").is_dir()]
    except OSError:
        return None
    if not installed:
        return None
    if running not in installed:
        same = [k for k in installed if _flavour(k) == _flavour(running)] or installed
        return max(same, key=_version)
    candidates = [k for k in installed if _flavour(k) == _flavour(running)]
    newest = max(candidates, key=_version)
    return newest if _version(newest) > _version(running) else None


def reboot_packages(flag: Path | None = None, packages: Path | None = None) -> list[str] | None:
    """What asked for a reboot (packages, or `kernel <release>`); None when no reboot is required."""
    flag = REBOOT_REQUIRED if flag is None else flag
    packages = REBOOT_PACKAGES if packages is None else packages
    found: set[str] = set()
    required = False
    if flag.exists():
        required = True
        try:
            found |= {p for p in packages.read_text(encoding="utf-8").split() if p}
        except OSError:
            pass
    if REBOOT_NEEDED.exists():
        required = True
    kernel = newer_kernel()
    if kernel is not None:
        required = True
        found.add(f"kernel {kernel}")
    return sorted(found) if required else None


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
