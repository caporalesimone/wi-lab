#!/usr/bin/env python3
"""Diagnose hostapd/AP startup failures for a configured Wi-Lab network."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class CmdResult:
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def run_cmd(cmd: list[str], timeout: float = 8.0) -> CmdResult:
    try:
        cp = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return CmdResult(cmd=cmd, returncode=cp.returncode, stdout=cp.stdout, stderr=cp.stderr)
    except subprocess.TimeoutExpired as exc:
        return CmdResult(
            cmd=cmd,
            returncode=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            timed_out=True,
        )


def print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def print_cmd_result(res: CmdResult) -> None:
    quoted = " ".join(shlex.quote(p) for p in res.cmd)
    print(f"$ {quoted}")
    if res.timed_out:
        print("exit: timeout")
    else:
        print(f"exit: {res.returncode}")
    if res.stdout.strip():
        print("stdout:")
        print(res.stdout.strip())
    if res.stderr.strip():
        print("stderr:")
        print(res.stderr.strip())


def load_interface_from_config(config_path: Path, net_id: str) -> str:
    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    networks = cfg.get("networks", [])
    for entry in networks:
        if entry.get("net_id") == net_id:
            iface = entry.get("interface")
            if not iface:
                raise ValueError(f"net_id '{net_id}' has no interface in config")
            return str(iface)
    raise ValueError(f"net_id '{net_id}' not found in config")


def find_driver_module(interface: str) -> Optional[str]:
    module_link = Path(f"/sys/class/net/{interface}/device/driver/module")
    if not module_link.exists():
        return None
    try:
        return module_link.resolve().name
    except OSError:
        return None


def contains_any(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(p.lower() in lowered for p in patterns)


def find_usb_device_sysfs(interface: str) -> Optional[Path]:
    """Return the USB device directory in sysfs for a network interface."""
    dev_link = Path(f"/sys/class/net/{interface}/device")
    if not dev_link.exists():
        return None
    try:
        resolved = dev_link.resolve()
        # Walk up to find USB device dir (e.g. 3-3, not 3-3:1.0)
        for candidate in [resolved] + list(resolved.parents):
            name = candidate.name
            if re.match(r"^\d+-[\d.]+$", name) and ":" not in name:
                if (candidate / "authorized").exists():
                    return candidate
    except OSError:
        pass
    return None


def try_soft_reset(interface: str) -> tuple[bool, list[CmdResult]]:
    """Bring interface down, set managed mode, bring it back up."""
    results: list[CmdResult] = []
    results.append(run_cmd(["ip", "link", "set", interface, "down"]))
    results.append(run_cmd(["iw", "dev", interface, "set", "type", "managed"]))
    up = run_cmd(["ip", "link", "set", interface, "up"])
    results.append(up)
    return up.returncode == 0, results


def try_usb_reset(interface: str) -> tuple[bool, list[str]]:
    """Soft USB replug via sysfs authorized 0 → 1 cycle."""
    usb_path = find_usb_device_sysfs(interface)
    notes: list[str] = []
    if not usb_path:
        notes.append("Could not find USB device sysfs path; skipping USB reset.")
        return False, notes
    authorized = usb_path / "authorized"
    notes.append(f"USB device sysfs: {usb_path}")
    try:
        authorized.write_text("0\n")
        time.sleep(1.5)
        authorized.write_text("1\n")
        time.sleep(2.5)
        notes.append("USB authorized cycle complete (0 → 1). Waiting for re-enumeration.")
        return True, notes
    except OSError as exc:
        notes.append(f"USB reset failed: {exc}")
        return False, notes


def try_driver_reload(module: str) -> tuple[bool, list[CmdResult]]:
    """Remove and reload the kernel driver module."""
    results: list[CmdResult] = []
    results.append(run_cmd(["modprobe", "-r", module]))
    time.sleep(1)
    load = run_cmd(["modprobe", module])
    results.append(load)
    time.sleep(1)
    return load.returncode == 0, results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose AP startup failures (hostapd code 1, interface busy, driver issues)."
    )
    parser.add_argument("--net-id", default="ap-03", help="Network id from config.yaml (default: ap-03)")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--hostapd-timeout",
        type=float,
        default=8.0,
        help="Seconds to wait for foreground hostapd debug run (default: 8)",
    )
    parser.add_argument(
        "--skip-hostapd-debug",
        action="store_true",
        help="Skip foreground hostapd debug execution.",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="Attempt automated interface recovery (requires root).",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}")
        return 2

    try:
        interface = load_interface_from_config(config_path, args.net_id)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    print("Wi-Lab AP Diagnostic")
    print(f"net_id: {args.net_id}")
    print(f"interface: {interface}")
    print(f"config: {config_path}")
    print(f"running_as_root: {os.geteuid() == 0}")

    findings: list[str] = []
    suggestions: list[str] = []
    driver_module = find_driver_module(interface)

    print_header("Interface State")
    ip_show = run_cmd(["ip", "-details", "link", "show", interface])
    print_cmd_result(ip_show)
    iw_info = run_cmd(["iw", "dev", interface, "info"])
    print_cmd_result(iw_info)

    print_header("NetworkManager Status")
    nmcli = run_cmd(["nmcli", "-t", "-f", "GENERAL.DEVICE,GENERAL.STATE,GENERAL.CONNECTION", "dev", "show", interface])
    print_cmd_result(nmcli)

    print_header("Try Bring Interface UP")
    ip_up = run_cmd(["ip", "link", "set", interface, "up"])
    print_cmd_result(ip_up)

    ip_up_blob = (ip_up.stdout or "") + "\n" + (ip_up.stderr or "")
    if contains_any(ip_up_blob, ["operation not permitted"]):
        findings.append("Insufficient privileges to bring interface UP during diagnostics.")
        suggestions.append("Run this diagnostic with sudo to execute full low-level checks.")
    elif contains_any(ip_up_blob, ["device or resource busy"]):
        findings.append("Interface cannot be brought UP: kernel reports 'Device or resource busy'.")
        suggestions.append("Reset/replug the USB adapter of this interface and retry.")

    hostapd_conf = Path(f"/tmp/wilab-hostapd/hostapd-{args.net_id}.conf")
    print_header("Hostapd Config")
    if hostapd_conf.exists():
        print(f"config_path: {hostapd_conf}")
        print(hostapd_conf.read_text(encoding="utf-8"))
    else:
        print(f"config file not found: {hostapd_conf}")
        findings.append("hostapd config file for this net_id is missing in /tmp/wilab-hostapd.")

    hostapd_debug: Optional[CmdResult] = None
    if not args.skip_hostapd_debug and hostapd_conf.exists():
        print_header("Hostapd Foreground Debug")
        hostapd_debug = run_cmd(["hostapd", "-dd", str(hostapd_conf)], timeout=args.hostapd_timeout)
        print_cmd_result(hostapd_debug)
        debug_blob = (hostapd_debug.stdout or "") + "\n" + (hostapd_debug.stderr or "")
        if contains_any(debug_blob, ["device or resource busy"]):
            findings.append("hostapd fails while setting interface UP (resource busy).")
        elif contains_any(debug_blob, ["operation not permitted"]):
            findings.append("hostapd debug run lacks required privileges (operation not permitted).")
            suggestions.append("Run this script as root to capture definitive hostapd startup diagnostics.")

        if contains_any(debug_blob, ["nl80211 driver initialization failed"]):
            findings.append("hostapd fails at nl80211 driver initialization.")

    print_header("Kernel / Driver Signals")
    if driver_module:
        print(f"driver_module: {driver_module}")
    else:
        print("driver_module: unknown")

    dmesg = run_cmd(["dmesg"])
    if dmesg.returncode == 0:
        patterns = [interface]
        if driver_module:
            patterns.append(driver_module)
        regex = re.compile("|".join(re.escape(p) for p in patterns), re.IGNORECASE)
        lines = [ln for ln in dmesg.stdout.splitlines() if regex.search(ln)]
        tail = lines[-80:]
        if tail:
            print("recent dmesg matches:")
            print("\n".join(tail))
        else:
            print("no recent dmesg lines matching interface/driver")

        joined = "\n".join(tail)
        if contains_any(joined, ["failed to download firmware", "failed to download rsvd page", "failed to get tx report"]):
            findings.append("Kernel reports driver/firmware failures on this WiFi adapter.")
            suggestions.append("Reload/update the WiFi driver module and check USB power stability.")
    else:
        print_cmd_result(dmesg)

    if args.recover:
        print_header("Interface Recovery Attempts")
        if os.geteuid() != 0:
            print("WARNING: Not running as root. Recovery operations may fail.")
            print("Re-run with sudo for full low-level access.\n")

        recovered = False

        print("\n-- Step 1: Soft reset (down → managed → up) --")
        ok1, cmds1 = try_soft_reset(interface)
        for r in cmds1:
            print_cmd_result(r)
        if ok1:
            print("✓ Interface UP after soft reset. Recovery successful.")
            recovered = True
        else:
            print("✗ Soft reset insufficient.")

        if not recovered:
            print("\n-- Step 2: USB device authorized cycle (driver-side replug) --")
            usb_ok, usb_notes = try_usb_reset(interface)
            for note in usb_notes:
                print(note)
            if usb_ok:
                print("Retrying soft reset after USB cycle...")
                ok2, cmds2 = try_soft_reset(interface)
                for r in cmds2:
                    print_cmd_result(r)
                if ok2:
                    print("✓ Interface UP after USB reset. Recovery successful.")
                    recovered = True
                else:
                    print("✗ Interface still not UP after USB reset.")

        if not recovered:
            print("\n-- Step 3: Driver module reload --")
            if driver_module:
                mod_ok, mod_cmds = try_driver_reload(driver_module)
                for r in mod_cmds:
                    print_cmd_result(r)
                if mod_ok:
                    time.sleep(2)
                    print("Retrying soft reset after driver reload...")
                    ok3, cmds3 = try_soft_reset(interface)
                    for r in cmds3:
                        print_cmd_result(r)
                    if ok3:
                        print("✓ Interface UP after driver reload. Recovery successful.")
                        recovered = True
                    else:
                        print("✗ Interface still not UP after driver reload.")
                else:
                    print("✗ Driver module reload failed.")
            else:
                print("Driver module unknown; skipping.")

        if not recovered:
            print("\n✗ All automated recovery steps exhausted.")
            print("Physical replug of the USB adapter is likely required.")

    print_header("Heuristic Diagnosis")
    if findings:
        for idx, item in enumerate(findings, start=1):
            print(f"{idx}. {item}")
    else:
        print("No definitive failure signature detected. Collect journalctl logs around startup time.")

    print_header("Recovery Actions")
    default_actions = [
        "Stop Wi-Lab service before low-level interface recovery.",
        "Run 'sudo python3 scripts/10-diagnose-ap.py --net-id <id> --recover' for automated recovery.",
        "Try: ip link set <iface> down; iw dev <iface> set type managed; ip link set <iface> up.",
        "If still busy: unplug/replug the USB adapter and retry network creation.",
        "If recurring: reload the driver module or upgrade kernel/driver for this chipset.",
        "If using multiple USB adapters: test powered USB hub / different port to avoid brown-outs.",
    ]
    merged = default_actions + suggestions
    deduped: list[str] = []
    for action in merged:
        if action not in deduped:
            deduped.append(action)

    for idx, item in enumerate(deduped, start=1):
        print(f"{idx}. {item}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
