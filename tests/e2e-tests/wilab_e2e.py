"""Helpers for the end-to-end tests: server actions and a small API client."""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

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

    def kill(self, pid: int) -> None:
        self.sudo(["kill", "-9", str(pid)])

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
    def hold_dhcp_port(self, interface: str) -> Iterator[None]:
        """Hold UDP port 67 on `interface` so dnsmasq cannot start there (a non-radio failure)."""
        script = (
            "import socket, sys\n"
            "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            "s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, sys.argv[1].encode())\n"
            "s.bind(('0.0.0.0', 67))\n"
            "print('ready', flush=True)\n"
            "sys.stdin.read()\n"
        )
        password = self.sudo_file.read_bytes().splitlines()[0]
        holder = subprocess.Popen(
            ["sudo", "-k", "-S", "-p", "", "python3", "-c", script, interface],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        assert holder.stdin is not None and holder.stdout is not None
        holder.stdin.write(password + b"\n")
        holder.stdin.flush()
        try:
            if holder.stdout.readline().strip() != b"ready":
                raise RuntimeError(f"Could not hold UDP port 67 on {interface}")
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

    def hostapd_config(self, interface: str) -> dict[str, str]:
        """`hostapd_cli get_config` of the AP on `interface` (HAP-10)."""
        socket = self.sudo_output(
            ["find", "/tmp/wilab-hostapd", "-type", "s", "-name", interface],
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
        """GET /antennas/{interface}: what a network on the antenna can use."""
        response = self.http.get(f"/antennas/{interface}")
        response.raise_for_status()
        return response.json()

    def offers(
        self, interface: str, band: str, channel: int, width: int, generation: int,
    ) -> bool:
        """True when the antenna lists this generation, width and channel together."""
        options = self.antenna(interface)["bands"][band]
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

    def create(self, antenna: Antenna, **overrides: Any) -> httpx.Response:
        body: dict[str, Any] = {
            "ssid": "wilab-e2e", "channel": 6, "band": "2.4ghz", "encryption": "wpa2",
            "password": "e2e-pass-123", "tx_power_level": 2,
        }
        body.update(overrides)
        body = {key: value for key, value in body.items() if value is not None}
        url = f"/reservations/{antenna.reservation_id}/network"
        response = self.http.post(url, json=network_body(**body))
        if response.status_code != 202:
            return response  # 200 (already running), or an error answered at once
        # Asynchronous create: poll until the start ends (the network, start_failed or 404).
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            time.sleep(1)
            response = self.http.get(url)
            if response.status_code != 200 or response.json().get("runtime_state") != "starting":
                return self._start_outcome(response)
        raise TimeoutError(f"{url} still starting after 360 s")

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

    def close(self) -> None:
        for rid in list(self.reserved):
            self.http.delete(f"/reservations/{rid}/network")
            self.http.delete(f"/reservations/{rid}")
        self.reserved.clear()
        self.http.close()


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
