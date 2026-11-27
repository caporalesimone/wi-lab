"""Helpers for the end-to-end tests: server actions and a small API client."""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

SERVICE = "wi-lab"


# --------------------------------------------------------------------------- server

@dataclass
class Server:
    """Actions on the Wi-Lab machine: journal, interfaces, simulated USB unplug."""

    sudo_file: Path
    unplugged: set[str] = field(default_factory=set)

    def sudo(self, args: list[str], data: bytes = b"") -> None:
        # -k: always read the password, so a cached sudo session never turns it into data.
        password = self.sudo_file.read_bytes().splitlines()[0]
        subprocess.run(
            ["sudo", "-k", "-S", "-p", "", *args], input=password + b"\n" + data,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30,
        )

    def sudo_output(self, args: list[str]) -> str:
        password = self.sudo_file.read_bytes().splitlines()[0]
        return subprocess.run(
            ["sudo", "-k", "-S", "-p", "", *args], input=password + b"\n",
            capture_output=True, check=True, timeout=30,
        ).stdout.decode()

    def iptables_rules(self, table: str = "filter") -> str:
        return self.sudo_output(["iptables", "-w", "5", "-t", table, "-S"])

    def ip6tables_rules(self, table: str = "filter") -> str:
        return self.sudo_output(["ip6tables", "-w", "5", "-t", table, "-S"])

    def wilab_rules(self, interface: str) -> list[str]:
        """Every iptables/ip6tables rule or chain Wi-Lab names after `interface`.

        Matches `wilab-in-`, `wilab-guard-`, `wilab-nat-`, `wilab-forward-`,
        `wilab-block-`, `wilab-cp-` and `wilab-captive-` followed by the interface,
        in the IPv4 filter and nat tables and the IPv6 filter table.
        """
        owned = re.compile(r"wilab-[a-z]+-" + re.escape(interface) + r"(?![\w-])")
        tables = (
            self.iptables_rules("filter"), self.iptables_rules("nat"), self.ip6tables_rules("filter"),
        )
        return [line for rules in tables for line in rules.splitlines() if owned.search(line)]

    def chain_rules(self, chain: str, table: str = "filter", ipv6: bool = False) -> list[str]:
        """The `-A <chain> ...` lines of one chain (empty if the chain does not exist)."""
        rules = self.ip6tables_rules(table) if ipv6 else self.iptables_rules(table)
        return [line for line in rules.splitlines() if line.startswith(f"-A {chain} ")]

    def remove_host_guard(self, interface: str) -> None:
        """Delete the `wilab-in-<interface>` jump from INPUT and the chain itself, IPv4 and IPv6."""
        chain = f"wilab-in-{interface}"
        for command, rules in (
            ("iptables", self.iptables_rules()), ("ip6tables", self.ip6tables_rules()),
        ):
            for line in rules.splitlines():
                tokens = shlex.split(line)
                if tokens[:2] == ["-A", "INPUT"] and tokens[-2:] == ["-j", chain]:
                    self.sudo([command, "-w", "5", "-D", *tokens[1:]])
            self.sudo([command, "-w", "5", "-F", chain])
            self.sudo([command, "-w", "5", "-X", chain])

    @staticmethod
    def listening_tcp() -> list[str]:
        """Local addresses (`ip:port`) of listening TCP sockets, from `ss`."""
        out = subprocess.run(["ss", "-Hltn"], capture_output=True, text=True, check=True).stdout
        return [line.split()[3] for line in out.splitlines() if len(line.split()) >= 4]

    @staticmethod
    def interface_present(interface: str) -> bool:
        return Path("/sys/class/net", interface).exists()

    @staticmethod
    def usb_port(interface: str) -> str:
        """USB port (for example 2-1) of a Wi-Fi interface, from sysfs."""
        function = (Path("/sys/class/net") / interface / "device").resolve(strict=True)
        return function.parent.name

    def set_usb_authorized(self, port: str, value: int) -> None:
        path = Path("/sys/bus/usb/devices") / port / "authorized"
        self.sudo(["tee", str(path)], str(value).encode())
        if path.read_text().strip() != str(value):
            raise RuntimeError(f"{path} is not {value}")
        if value == 0:
            self.unplugged.add(port)
        else:
            self.unplugged.discard(port)

    def wait_interface(self, interface: str, present: bool = True, timeout: float = 30) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.interface_present(interface) == present:
                return True
            time.sleep(0.5)
        return False

    @staticmethod
    def pids(name: str) -> list[int]:
        out = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True, check=False).stdout
        return [int(pid) for pid in out.split()]

    def kill(self, pid: int, signal: str = "KILL") -> None:
        self.sudo(["kill", f"-{signal}", str(pid)])

    @staticmethod
    def dnsmasq_pids(interface: str) -> list[int]:
        """PIDs of the dnsmasq Wi-Lab runs for the network on `interface`."""
        out = subprocess.run(
            ["pgrep", "-f", f"dnsmasq .*--conf-file=.*dnsmasq-{interface}\\.conf"],
            capture_output=True, text=True, check=False,
        ).stdout
        return [int(pid) for pid in out.split()]

    @staticmethod
    def qdiscs(interface: str) -> str:
        return subprocess.run(
            ["tc", "qdisc", "show", "dev", interface], capture_output=True, text=True, check=True,
        ).stdout

    @staticmethod
    def wilab_ifbs() -> list[str]:
        out = subprocess.run(
            ["ip", "-o", "link", "show", "type", "ifb"], capture_output=True, text=True, check=True,
        ).stdout
        names = [line.split(":")[1].strip().split("@")[0] for line in out.splitlines() if ":" in line]
        return [name for name in names if name.startswith("wilab-ifb")]

    @staticmethod
    def ipv4_addresses(interface: str) -> list[str]:
        out = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "dev", interface], capture_output=True, text=True, check=True,
        ).stdout
        return [w for line in out.splitlines() for w in line.split() if "/" in w and w[0].isdigit()]

    def kill_service_main(self) -> None:
        """SIGKILL only the main process: an unclean shutdown, then Restart=always."""
        self.sudo(["systemctl", "kill", "--kill-whom=main", "--signal=SIGKILL", SERVICE])

    def service_resources(self) -> dict[str, int]:
        """PID, resident memory (kB), open descriptors and threads of the service's main process."""
        pid = int(subprocess.run(
            ["systemctl", "show", SERVICE, "-p", "MainPID", "--value"], capture_output=True, text=True, check=True,
        ).stdout.strip())
        fields = dict(
            line.split(":", 1) for line in Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in line
        )
        return {
            "pid": pid,
            "rss_kb": int(fields["VmRSS"].split()[0]),
            "threads": int(fields["Threads"]),
            "fds": len(self.sudo_output(["ls", f"/proc/{pid}/fd"]).split()),   # root only
        }

    @staticmethod
    def service_started_at() -> float:
        stamp = subprocess.run(
            ["systemctl", "show", SERVICE, "-p", "ActiveEnterTimestamp", "--value"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(subprocess.run(
            ["date", "-d", stamp, "+%s"], capture_output=True, text=True, check=True,
        ).stdout)

    def budget_used(self, interface: str, kind: str) -> int:
        """Watchdog AP restores (`kind="AP"`) or DHCP restarts (`"DHCP"`) on `interface`
        in the last hour of this service run. Both budgets are 3 per hour per antenna
        and live in the service, so earlier tests (or runs) consume them."""
        marker = {"AP": f"Restoring AP on {interface} (", "DHCP": f"Restarting DHCP on {interface} ("}[kind]
        since = max(time.time() - 3600, self.service_started_at())
        return self.journal(since).count(marker)

    @contextmanager
    def hold_dhcp_port(self, interface: str, wait: float = 60.0) -> Iterator[None]:
        """Hold UDP port 67 on `interface` so dnsmasq cannot start there (a non-radio failure).

        dnsmasq of a running network already holds `0.0.0.0%<interface>:67`, so the
        holder cannot take the port first: cause the failure, then enter this. The
        holder retries the bind every 20 ms for up to `wait` seconds and gets the
        port the moment the service stops that dnsmasq, before it starts it again.
        """
        script = (
            "import socket, sys, time\n"
            "end = time.monotonic() + float(sys.argv[2])\n"
            "while True:\n"
            "    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            "    s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, sys.argv[1].encode())\n"
            "    try:\n"
            "        s.bind(('0.0.0.0', 67))\n"
            "        break\n"
            "    except OSError as exc:\n"
            "        s.close()\n"
            "        if time.monotonic() > end:\n"
            "            print(exc, flush=True)\n"
            "            sys.exit(1)\n"
            "        time.sleep(0.02)\n"
            "print('ready', flush=True)\n"
            "sys.stdin.read()\n"
        )
        password = self.sudo_file.read_bytes().splitlines()[0]
        holder = subprocess.Popen(
            ["sudo", "-k", "-S", "-p", "", "python3", "-c", script, interface, str(wait)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        assert holder.stdin is not None and holder.stdout is not None
        holder.stdin.write(password + b"\n")
        holder.stdin.flush()
        try:
            answer = holder.stdout.readline().strip()
            if answer != b"ready":
                raise RuntimeError(f"Could not hold UDP port 67 on {interface}: {answer.decode()}")
            yield
        finally:
            holder.stdin.close()  # the holder exits at end of input
            holder.wait(timeout=10)

    @staticmethod
    def iptables_backend() -> str:
        out = subprocess.run(["iptables", "--version"], capture_output=True, text=True, check=False).stdout
        return "legacy" if "legacy" in out else "nf_tables"

    @contextmanager
    def hold_xtables_lock(self, seconds: float) -> Iterator[None]:
        """Hold the legacy xtables lock for `seconds` in the background, like Docker or ufw would."""
        password = self.sudo_file.read_bytes().splitlines()[0]
        holder = subprocess.Popen(
            ["sudo", "-k", "-S", "-p", "", "flock", "/run/xtables.lock", "sleep", str(seconds)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        assert holder.stdin is not None
        holder.stdin.write(password + b"\n")
        holder.stdin.close()
        time.sleep(0.5)  # let flock take the lock
        try:
            yield
        finally:
            holder.wait(timeout=seconds + 10)

    @staticmethod
    def journal(since: float) -> str:
        return subprocess.run(
            ["journalctl", "-u", SERVICE, "--since", f"@{int(since)}", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, check=True,
        ).stdout

    @staticmethod
    def iw_channel_width(interface: str) -> int | None:
        """Channel width in MHz the radio reports (HAP-11)."""
        out = subprocess.run(
            ["iw", "dev", interface, "info"], check=False, capture_output=True, text=True,
        ).stdout
        match = re.search(r"width:\s+(\d+)\s+MHz", out)
        return int(match[1]) if match else None

    def hostapd_pid(self, interface: str) -> int | None:
        """PID of the hostapd Wi-Lab runs on `interface`, from its private instance directory."""
        sockets = self.sudo_output(["find", "/run/wilab/hostapd", "-type", "s", "-name", interface]).split()
        if not sockets:
            return None
        instance = str(Path(sockets[0]).parent.parent)
        out = subprocess.run(["pgrep", "-af", "^hostapd "], capture_output=True, text=True, check=False).stdout
        for line in out.splitlines():
            pid, _, command = line.partition(" ")
            if f"{instance}/" in command:
                return int(pid)
        return None

    def hostapd_config(self, interface: str) -> dict[str, str]:
        """`hostapd_cli get_config` of the AP on `interface` (HAP-10)."""
        socket = self.sudo_output(
            ["find", "/run/wilab/hostapd", "-type", "s", "-name", interface],
        ).split()[0]
        out = self.sudo_output(
            ["hostapd_cli", "-p", str(Path(socket).parent), "-i", interface, "get_config"],
        )
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    @staticmethod
    def iw_txpower_dbm(interface: str) -> float | None:
        out = subprocess.run(
            ["iw", "dev", interface, "info"], check=False, capture_output=True, text=True,
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if parts[:1] == ["txpower"] and len(parts) >= 2:
                return float(parts[1])
        return None

    @staticmethod
    def iw_info(interface: str) -> dict[str, str]:
        out = subprocess.run(["iw", "dev", interface, "info"], check=False, capture_output=True, text=True).stdout
        info: dict[str, str] = {}
        for line in out.splitlines():
            key, _, value = line.strip().partition(" ")
            if key in ("ssid", "type", "channel"):
                info[key] = value
        return info


# --------------------------------------------------------------------------- API

_RADIO_FIELDS = ("band", "channel", "channel_width", "wifi_generation", "tx_power_level")


def network_body(**flat: Any) -> dict[str, Any]:
    """The sectioned create body (radio, wifi, internet, captive_portal) from flat fields.

    Tests pass flat overrides; unknown keys stay at the top level so invalid
    bodies can still be sent.
    """
    body: dict[str, Any] = {}
    radio = {key: flat.pop(key) for key in _RADIO_FIELDS if key in flat}
    security = {key: flat.pop(key) for key in ("encryption", "password") if key in flat}
    wifi: dict[str, Any] = {key: flat.pop(key) for key in ("ssid", "hidden") if key in flat}
    if security:
        wifi["security"] = security
    if radio:
        body["radio"] = radio
    if wifi:
        body["wifi"] = wifi
    if "internet_enabled" in flat:
        body["internet"] = {"enabled": flat.pop("internet_enabled")}
    if "captive_portal" in flat:
        body["captive_portal"] = {"enabled": flat.pop("captive_portal")}
    body.update(flat)
    return body


@dataclass
class Antenna:
    reservation_id: str
    interface: str
    display_name: str


class WiLab:
    """Thin API client that releases everything it reserved."""

    def __init__(self, base_url: str, token: str) -> None:
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v2",
            headers={"Authorization": f"Bearer {token}"}, timeout=120,
            # uvicorn closes an idle connection after 5 s; a client that reuses one at
            # that instant gets "Server disconnected". Drop idle connections sooner.
            limits=httpx.Limits(keepalive_expiry=2),
        )
        self.reserved: list[str] = []

    def status(self) -> dict[str, Any]:
        response = self.http.get("/status")
        response.raise_for_status()
        return response.json()

    def device(self, interface: str) -> dict[str, Any]:
        for entry in self.status()["antennas"]:
            if entry["interface"] == interface:
                return entry
        raise KeyError(interface)

    def antenna(self, interface: str) -> dict[str, Any]:
        """GET /antennas/{interface}: the antenna now (attachment, state, health)."""
        response = self.http.get(f"/antennas/{interface}")
        response.raise_for_status()
        return response.json()

    def capabilities(self, interface: str) -> dict[str, Any]:
        """GET /antennas/{interface}/capabilities: what a network on the antenna can use."""
        response = self.http.get(f"/antennas/{interface}/capabilities")
        response.raise_for_status()
        return response.json()

    def offers(
        self, interface: str, band: str, channel: int, width: int, generation: int,
    ) -> bool:
        """True when the antenna lists this generation, width and channel together."""
        options = self.capabilities(interface)["bands"][band]
        widths: list[int] = next((g["channel_widths"] for g in options["wifi_generations"]
                       if g["wifi_generation"] == generation), [])
        return width in widths and any(
            c["channel"] == channel and width in c["channel_widths"] for c in options["channels"]
        )

    def interfaces(self) -> list[str]:
        return [entry["interface"] for entry in self.status()["antennas"]]

    def reserve(self, interface: str | None = None, duration: int = 3600) -> Antenna:
        """Reserve an antenna: the given one, or the first free one."""
        body: dict[str, Any] = {"duration_seconds": duration}
        if interface is not None:
            body["interface"] = interface
        response = self.http.post("/reservations", json=body)
        response.raise_for_status()
        data = response.json()
        self.reserved.append(data["reservation_id"])
        return Antenna(data["reservation_id"], data["interface"], data["display_name"])

    def release(self, antenna: Antenna) -> None:
        self.http.delete(f"/reservations/{antenna.reservation_id}/network")
        self.http.delete(f"/reservations/{antenna.reservation_id}")
        if antenna.reservation_id in self.reserved:
            self.reserved.remove(antenna.reservation_id)

    def post_network(self, antenna: Antenna, **overrides: Any) -> httpx.Response:
        """The create `POST` alone, with the default body plus `overrides` (None drops a field)."""
        body: dict[str, Any] = {
            "ssid": "wilab-e2e", "channel": 6, "band": "2.4ghz", "encryption": "wpa2",
            "password": "e2e-pass-123", "tx_power_level": 2,
        }
        body.update(overrides)
        body = {key: value for key, value in body.items() if value is not None}
        return self.http.post(f"/reservations/{antenna.reservation_id}/network", json=network_body(**body))

    def network(self, antenna: Antenna) -> httpx.Response:
        return self.http.get(f"/reservations/{antenna.reservation_id}/network")

    def wait_start(self, antenna: Antenna, timeout: float = 360) -> httpx.Response:
        """Poll GET .../network until `runtime_state` is no longer `starting`; the raw answer."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(1)
            response = self.network(antenna)
            if response.status_code != 200 or response.json().get("runtime_state") != "starting":
                return response
        raise TimeoutError(f"{antenna.interface} still starting after {timeout:.0f} s")

    def create(self, antenna: Antenna, **overrides: Any) -> httpx.Response:
        response = self.post_network(antenna, **overrides)
        if response.status_code != 202:
            return response  # 200 (already running), or an error answered at once
        # Asynchronous create: poll until the start ends (the network, start_failed or 404).
        return self._start_outcome(self.wait_start(antenna))

    @staticmethod
    def _start_outcome(response: httpx.Response) -> httpx.Response:
        """The polled end of a start, so that `status_code == 200` means "the network is up".

        GET .../network answers 200 also when the start failed (`runtime_state:
        start_failed` with `error`) or left no network: that is returned as a 500
        whose `detail` is the error (code 1013), which `detail_code` reads.
        """
        if response.status_code != 200 or response.json().get("active") is True:
            return response
        state = response.json()
        detail = state.get("error") or {
            "code": 500, "reason": state.get("runtime_state") or "network_not_active",
            "message": f"The start ended without a network: {state}",
        }
        return httpx.Response(500, json={"detail": detail}, request=response.request)

    def delete_network(self, antenna: Antenna) -> int:
        return self.http.delete(f"/reservations/{antenna.reservation_id}/network").status_code

    def gone_answers(self, reservation_id: str) -> dict[str, tuple[int, str | None]]:
        """Status and `detail.reason` of every call that takes a reservation ID.

        Meant for an ID that is gone: each call then answers 404 before looking
        at the body, so the bodies only need to be valid.
        """
        base = f"/reservations/{reservation_id}"
        create = network_body(ssid="wilab-e2e-gone", channel=6, band="2.4ghz", encryption="open", tx_power_level=2)
        calls = {
            "GET": lambda: self.http.get(base),
            "GET network": lambda: self.http.get(f"{base}/network"),
            "POST network": lambda: self.http.post(f"{base}/network", json=create),
            "DELETE network": lambda: self.http.delete(f"{base}/network"),
            "GET txpower": lambda: self.http.get(f"{base}/txpower"),
            "POST txpower": lambda: self.http.post(f"{base}/txpower", json={"tx_power_level": 2}),
            "POST internet/enable": lambda: self.http.post(f"{base}/internet/enable"),
            "DELETE": lambda: self.http.delete(base),
        }
        answers = {}
        for name, call in calls.items():
            response = call()
            answers[name] = (response.status_code, gone_reason(response))
        return answers

    def close(self) -> None:
        for rid in list(self.reserved):
            self.http.delete(f"/reservations/{rid}/network")
            self.http.delete(f"/reservations/{rid}")
        self.reserved.clear()
        self.http.close()


def gone_reason(response: httpx.Response) -> str | None:
    """`detail.reason` of a 404 on a call with a reservation ID; None for any other answer."""
    if response.status_code != 404:
        return None
    detail = response.json().get("detail")
    return detail.get("reason") if isinstance(detail, dict) else None


def parse_utc(stamp: str) -> float:
    """Unix seconds of an RFC 3339 UTC timestamp as the API writes it (Z suffix)."""
    return datetime.fromisoformat(stamp).timestamp()


WATCHDOG_BUDGET = 3  # AP restores, and DHCP restarts, per hour per antenna


def reserve_with_budget(wilab: WiLab, server: Server, ap: int = 0, dhcp: int = 0) -> Antenna:
    """Reserve an antenna with `ap` AP restores and `dhcp` DHCP restarts left this hour; else skip.

    The watchdog budgets live in the running service and are read from the journal.
    """
    for entry in wilab.status()["antennas"]:
        interface = entry["interface"]
        if entry.get("recovery_state"):
            continue
        if (
            server.budget_used(interface, "AP") + ap <= WATCHDOG_BUDGET
            and server.budget_used(interface, "DHCP") + dhcp <= WATCHDOG_BUDGET
        ):
            return wilab.reserve(interface=interface)
    pytest.skip(
        f"no antenna has {ap} AP restores and {dhcp} DHCP restarts left this hour; "
        "wait or restart the service",
    )


def detail_code(response: httpx.Response) -> int | None:
    if response.status_code == 200:
        return None
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


def wait_for(predicate: Any, timeout: float, interval: float = 5) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())
