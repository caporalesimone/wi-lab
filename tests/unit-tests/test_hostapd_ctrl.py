"""PERF-4: the persistent control connection to hostapd, against a fake hostapd.

The fake is a real Unix datagram socket that answers like hostapd's control
interface (PING, ATTACH, STATUS, STA-FIRST/STA-NEXT) and sends events to the
attached clients. It can crash (the socket closes and its file stays, as after
a SIGSEGV), hang (no answers), and come back with other stations.
"""

import os
import shutil
import socket
import tempfile
import threading
import time
from unittest.mock import Mock

import pytest

from wilab.wifi import hostapd, hostapd_ctrl
from wilab.wifi.hostapd_ctrl import ControlError, HostapdMonitor


class FakeHostapd:
    def __init__(self, path: str, interface: str = "wlan0") -> None:
        self.path = path
        self.interface = interface
        self.stations: list[str] = []
        self.state = "ENABLED"
        self.attached: set[str] = set()
        self.commands: list[str] = []
        self.hung = False
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.start()

    def start(self) -> None:
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.attached = set()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(self.path)
        sock.settimeout(0.05)
        self._sock = sock
        self._thread = threading.Thread(target=self._serve, args=(sock,), daemon=True)
        self._thread.start()

    def crash(self) -> None:
        """Like a SIGSEGV: the socket goes away, its file stays on disk."""
        sock, self._sock = self._sock, None
        if sock is not None:
            sock.close()
        if self._thread is not None:
            self._thread.join(1)

    def restart(self, stations: list[str]) -> None:
        self.stations = list(stations)
        self.commands = []
        self.start()

    def event(self, text: str) -> None:
        for client in list(self.attached):
            try:
                assert self._sock is not None
                self._sock.sendto(f"<2>{text}".encode(), client)
            except OSError:
                self.attached.discard(client)

    def count(self, command: str) -> int:
        return sum(1 for c in self.commands if c.split()[0] == command)

    def _answer(self, command: str, client: str) -> str:
        words = command.split()
        if words[0] == "PING":
            return "PONG\n"
        if words[0] == "ATTACH":
            self.attached.add(client)
            return "OK\n"
        if words[0] == "STATUS":
            return f"state={self.state}\nbss[0]={self.interface}\nssid[0]=fake\n"
        if words[0] == "STA-FIRST":
            return f"{self.stations[0]}\nflags=[AUTH][ASSOC]\n" if self.stations else ""
        if words[0] == "STA-NEXT":
            index = self.stations.index(words[1]) + 1 if words[1] in self.stations else len(self.stations)
            return f"{self.stations[index]}\nflags=[AUTH]\n" if index < len(self.stations) else ""
        return "UNKNOWN COMMAND\n"

    def _serve(self, sock: socket.socket) -> None:
        while self._sock is sock:
            try:
                data, client = sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            command = data.decode()
            self.commands.append(command)
            if self.hung:
                continue
            try:
                sock.sendto(self._answer(command, client).encode(), client)
            except OSError:
                pass


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(hostapd_ctrl, "PING_INTERVAL", 0.1)
    monkeypatch.setattr(hostapd_ctrl, "PING_TIMEOUT", 0.2)
    monkeypatch.setattr(hostapd_ctrl, "RECONNECT_BACKOFF", (0.02, 0.05, 0.1))


@pytest.fixture
def directory():
    # Unix socket paths are limited to 108 bytes: pytest's tmp_path can be longer.
    path = tempfile.mkdtemp(prefix="wl-", dir="/tmp")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def fake(directory):
    server = FakeHostapd(os.path.join(directory, "wlan0"))
    server.stations = ["aa:00:00:00:00:01", "aa:00:00:00:00:02"]
    yield server
    server.crash()


@pytest.fixture
def monitor_of(directory):
    monitors: list[HostapdMonitor] = []

    def make(fake: FakeHostapd, on_change=None) -> HostapdMonitor:
        monitor = HostapdMonitor(fake.path, directory, "wlan0", on_change=on_change)
        monitors.append(monitor)
        monitor.start()
        return monitor

    yield make
    for monitor in monitors:
        monitor.close()


def until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_connects_attaches_and_reads_the_stations(fake, monitor_of):
    monitor = monitor_of(fake)
    assert monitor.wait_connected(2)
    assert fake.count("ATTACH") == 1
    assert monitor.stations() == {"aa:00:00:00:00:01", "aa:00:00:00:00:02"}
    assert monitor.enabled() is True
    assert monitor.status()["state"] == "ENABLED"


def test_events_update_the_stations_and_the_ap_state(fake, monitor_of):
    changed = Mock()
    monitor = monitor_of(fake, on_change=changed)
    assert monitor.wait_connected(2)
    fake.event("AP-STA-CONNECTED aa:00:00:00:00:03")
    fake.event("AP-STA-DISCONNECTED aa:00:00:00:00:01")
    assert until(lambda: monitor.stations() == {"aa:00:00:00:00:02", "aa:00:00:00:00:03"})
    fake.event("AP-DISABLED ")
    assert until(lambda: monitor.enabled() is False)
    assert until(lambda: changed.call_count == 1)


def test_reconnects_after_a_crash_attaches_again_and_rebuilds_the_stations(fake, monitor_of):
    """Point 2 and 3: lost -> backoff -> reconnect -> ATTACH -> full station list read again."""
    changed = Mock()
    monitor = monitor_of(fake, on_change=changed)
    assert monitor.wait_connected(2)
    fake.crash()
    assert until(lambda: not monitor.connected)
    assert monitor.stations() is None   # unknown while not connected: readers fall back
    assert until(lambda: changed.call_count >= 1)   # the watchdog is woken
    with pytest.raises(ControlError):
        monitor.request("STATUS")
    time.sleep(0.3)   # a few failed reconnections against the stale socket file
    assert not monitor.connected
    # hostapd comes back; a station joined and one left during the gap
    fake.restart(["aa:00:00:00:00:02", "bb:00:00:00:00:09"])
    assert until(lambda: monitor.connected)
    assert fake.count("ATTACH") == 1   # counted since the restart: attached again
    assert monitor.connections == 2
    assert monitor.stations() == {"aa:00:00:00:00:02", "bb:00:00:00:00:09"}
    fake.event("AP-STA-CONNECTED cc:00:00:00:00:01")   # events flow again
    assert until(lambda: "cc:00:00:00:00:01" in (monitor.stations() or set()))


def test_a_ping_without_answer_means_lost(fake, monitor_of):
    monitor = monitor_of(fake)
    assert monitor.wait_connected(2)
    fake.hung = True
    assert until(lambda: not monitor.connected, timeout=2)
    fake.hung = False
    assert until(lambda: monitor.connected, timeout=2)
    assert monitor.connections == 2


def test_keeps_trying_while_hostapd_is_not_there(directory, monitor_of):
    path = os.path.join(directory, "wlan0")
    absent = FakeHostapd(path)
    absent.crash()
    os.unlink(path)
    monitor = monitor_of(absent)
    time.sleep(0.4)
    assert not monitor.connected
    absent.restart(["aa:00:00:00:00:01"])
    assert until(lambda: monitor.connected)
    absent.crash()


def test_close_stops_the_thread_and_removes_the_client_sockets(fake, monitor_of, directory):
    monitor = monitor_of(fake)
    assert monitor.wait_connected(2)
    assert any(name.startswith("wilab-") for name in os.listdir(directory))
    monitor.close()
    assert monitor._thread is not None and not monitor._thread.is_alive()
    assert not any(name.startswith("wilab-") for name in os.listdir(directory))
    fake.crash()
    time.sleep(0.2)
    assert monitor.connections == 1   # never reconnects after close


# ----------------------------------------------------------------------------- HostapdManager


@pytest.fixture
def instance(directory):
    """hostapd's layout: <instance>/ctrl/<interface>; the monitor's sockets go in <instance>."""
    instance_dir = os.path.join(directory, "ap-test")
    os.makedirs(os.path.join(instance_dir, "ctrl"))
    server = FakeHostapd(os.path.join(instance_dir, "ctrl", "wlan0"))
    server.stations = ["aa:00:00:00:00:01"]
    yield server, instance_dir
    server.crash()


def _manager_with_monitor(fake: FakeHostapd, instance_dir: str) -> hostapd.HostapdManager:
    manager = hostapd.HostapdManager()
    process = Mock()
    process.poll.return_value = None
    monitor = HostapdMonitor(fake.path, instance_dir, "wlan0")
    monitor.start()
    manager._instances["net"] = {
        "interface": "wlan0", "config_file": os.path.join(instance_dir, "hostapd.conf"),
        "control_dir": os.path.join(instance_dir, "ctrl"),
        "ssid": "fake", "process": process, "monitor": monitor,
    }
    return manager


def test_is_enabled_uses_the_connection_and_falls_back_to_hostapd_cli(instance, monkeypatch):
    fake, instance_dir = instance
    calls = []

    def hostapd_cli(cmd, **kwargs):
        calls.append(cmd)
        return "state=ENABLED\nbss[0]=wlan0\n"

    monkeypatch.setattr(hostapd, "execute_command", hostapd_cli)
    manager = _manager_with_monitor(fake, instance_dir)
    monitor = manager._instances["net"]["monitor"]
    assert monitor is not None and monitor.wait_connected(2)
    assert manager.is_enabled("net") is True
    assert calls == []   # no process for the probe
    assert manager.stations("net") == set(fake.stations)
    fake.crash()
    assert until(lambda: not monitor.connected)
    assert manager.is_enabled("net") is True   # hostapd_cli answered
    assert calls and calls[0][0] == "hostapd_cli"
    monitor.close()


def test_stop_closes_the_monitor_before_the_process(instance, monkeypatch):
    fake, instance_dir = instance
    monkeypatch.setattr(hostapd, "interface_present", lambda _interface: False)
    manager = _manager_with_monitor(fake, instance_dir)
    monitor = manager._instances["net"]["monitor"]
    assert monitor is not None and monitor.wait_connected(2)
    order = []
    process = manager._instances["net"]["process"]
    process.stop.side_effect = lambda: order.append(("process", monitor._closed.is_set()))
    manager.stop("net")
    assert order == [("process", True)]
    assert monitor._thread is not None and not monitor._thread.is_alive()
    assert not os.path.exists(instance_dir)   # client sockets gone before the rmdir


def test_a_lost_connection_wakes_the_watchdog_of_the_antenna(fake, directory):
    woken = []
    manager = hostapd.HostapdManager(on_change=woken.append)
    monitor = HostapdMonitor(fake.path, directory, "wlan0", on_change=lambda: manager._changed("wlan0"))
    monitor.start()
    try:
        assert monitor.wait_connected(2)
        fake.crash()
        assert until(lambda: woken == ["wlan0"])
    finally:
        monitor.close()
