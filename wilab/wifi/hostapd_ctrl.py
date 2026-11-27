"""Persistent connection to the control interface of one hostapd (PERF-4).

hostapd's control interface is a Unix datagram socket in the instance's private
control directory. A client binds its own socket, sends a command and reads the
reply; after `ATTACH` it also receives events (`<2>AP-STA-CONNECTED ...`).

The `HostapdMonitor` of a network holds two such sockets for the life of the
network, so the watchdog's status probe no longer starts a `hostapd_cli`
process every 5 s, and events arrive as they happen:

- `connected`: events update the station list and the AP state; a `PING`
  without an answer within PING_TIMEOUT, or any socket error, means `lost`.
- `lost`: the sockets are closed and the monitor reconnects with a backoff
  (RECONNECT_BACKOFF, then the last value forever) until the network is
  stopped (`close`). After each reconnection it sends `ATTACH` again and
  rebuilds the station list with `STA-FIRST`/`STA-NEXT`: events lost during
  the gap never come back.

A crash of hostapd is detected from the process (`poll()`), not from the
socket: the socket file can stay on disk after hostapd died. The monitor only
makes it faster: on `lost` and on `AP-DISABLED` it calls *on_change*, which
wakes the watchdog of the antenna. When the monitor is not connected every
reader falls back to the one-shot `hostapd_cli` of before, so the API never
depends on this connection.
"""

from __future__ import annotations

import contextlib
import itertools
import logging
import os
import socket
import threading
import time
from collections.abc import Callable

from .. import log

logger = logging.getLogger(__name__)

PING_INTERVAL = 2.0       # seconds without any message from hostapd before a PING
PING_TIMEOUT = 1.0        # a PING without an answer in this time: connection lost
REQUEST_TIMEOUT = 1.0     # default wait for the reply to a command
RECONNECT_BACKOFF = (0.2, 0.5, 1.0, 2.0)   # then 2 s forever, while the network exists
STATION_LIMIT = 4096      # STA-NEXT walk limit: a confused hostapd cannot keep us looping
_RECV_SIZE = 65536


class ControlError(Exception):
    """The control socket did not answer, or is not connected."""


class ControlSocket:
    """One client socket bound in *directory* and connected to hostapd's socket at *server_path*."""

    _sequence = itertools.count()

    def __init__(self, server_path: str, directory: str, role: str) -> None:
        self.path = os.path.join(directory, f"wilab-{role}-{os.getpid()}-{next(self._sequence)}")
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.path)
            self._sock.bind(self.path)
            self._sock.connect(server_path)
        except OSError as exc:
            self.close()
            raise ControlError(f"cannot connect to {server_path}: {exc}") from exc

    def request(self, command: str, timeout: float = REQUEST_TIMEOUT) -> str:
        """Send *command* and return its reply; events received meanwhile are skipped."""
        deadline = time.monotonic() + timeout
        try:
            self._sock.send(command.encode())
            while (remaining := deadline - time.monotonic()) > 0:
                self._sock.settimeout(remaining)
                reply = self._sock.recv(_RECV_SIZE).decode(errors="replace")
                if not reply.startswith("<"):   # "<N>..." is an event, not our reply
                    return reply
        except TimeoutError as exc:
            raise ControlError(f"no reply to {command.split()[0]} within {timeout:.1f} s") from exc
        except OSError as exc:
            raise ControlError(f"{command.split()[0]} failed: {exc}") from exc
        raise ControlError(f"no reply to {command.split()[0]} within {timeout:.1f} s")

    def receive(self, timeout: float) -> str | None:
        """The next message within *timeout*, or None."""
        try:
            self._sock.settimeout(timeout)
            return self._sock.recv(_RECV_SIZE).decode(errors="replace")
        except TimeoutError:
            return None
        except OSError as exc:
            raise ControlError(f"receive failed: {exc}") from exc

    def close(self) -> None:
        self._sock.close()
        with contextlib.suppress(OSError):
            os.unlink(self.path)


def parse_fields(reply: str) -> dict[str, str]:
    """`key=value` lines of a STATUS reply."""
    return dict(line.split("=", 1) for line in reply.splitlines() if "=" in line)


class HostapdMonitor:
    """The persistent connection to one hostapd; see the module docstring."""

    def __init__(
        self, server_path: str, client_dir: str, interface: str,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.server_path = server_path
        self.client_dir = client_dir
        self.interface = interface
        self._on_change = on_change
        self._lock = threading.Lock()        # the request socket and the state below
        self._closed = threading.Event()
        self._connected = threading.Event()
        self._events: ControlSocket | None = None
        self._requests: ControlSocket | None = None
        self._stations: set[str] = set()
        self._enabled: bool | None = None
        self.connections = 0                 # successful connections, the first included
        self._thread: threading.Thread | None = None
        self._log_context = log.current()

    # ------------------------------------------------------------------ public

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"hostapd-ctrl-{self.interface}", daemon=True,
        )
        self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        """Stop the monitor and remove its sockets; it never reconnects after this."""
        self._closed.set()
        with self._lock:
            self._drop()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def wait_connected(self, timeout: float) -> bool:
        return self._connected.wait(timeout)

    def request(self, command: str, timeout: float = REQUEST_TIMEOUT) -> str:
        """A command on the persistent socket; ControlError when not connected or no reply."""
        with self._lock:
            if self._requests is None or not self._connected.is_set():
                raise ControlError("control connection not established")
            try:
                return self._requests.request(command, timeout)
            except ControlError:
                self._lose("request failed")
                raise

    def status(self, timeout: float = REQUEST_TIMEOUT) -> dict[str, str]:
        return parse_fields(self.request("STATUS", timeout))

    def stations(self) -> set[str] | None:
        """MAC addresses of the associated stations; None while not connected."""
        with self._lock:
            return set(self._stations) if self._connected.is_set() else None

    def enabled(self) -> bool | None:
        """The AP state from the last STATUS or AP-ENABLED/AP-DISABLED event; None when unknown."""
        with self._lock:
            return self._enabled if self._connected.is_set() else None

    # ------------------------------------------------------------------ thread

    def _run(self) -> None:
        log.bind(antenna=self._log_context[0] or self.interface, reservation=self._log_context[1])
        failures = 0
        while not self._closed.is_set():
            if not self._connected.is_set():
                if self._connect():
                    failures = 0
                    continue
                delay = RECONNECT_BACKOFF[min(failures, len(RECONNECT_BACKOFF) - 1)]
                failures += 1
                self._closed.wait(delay)
                continue
            self._listen()

    def _connect(self) -> bool:
        events = requests = None
        try:
            events = ControlSocket(self.server_path, self.client_dir, "mon")
            if events.request("ATTACH").strip() != "OK":
                raise ControlError("ATTACH refused")
            requests = ControlSocket(self.server_path, self.client_dir, "req")
            enabled = parse_fields(requests.request("STATUS")).get("state") == "ENABLED"
            stations = self._read_stations(requests)
        except ControlError as exc:
            for sock in (events, requests):
                if sock is not None:
                    sock.close()
            logger.debug("Control connection to hostapd on %s not ready: %s", self.interface, exc)
            return False
        with self._lock:
            if self._closed.is_set():
                events.close()
                requests.close()
                return False
            self._events, self._requests = events, requests
            self._stations, self._enabled = stations, enabled
            self.connections += 1
            self._connected.set()
        if self.connections > 1:
            logger.info(
                "Control connection to hostapd on %s restored (%d stations, AP %s)",
                self.interface, len(stations), "enabled" if enabled else "not enabled",
            )
        return True

    @staticmethod
    def _read_stations(requests: ControlSocket) -> set[str]:
        """The full station list, read again after every (re)connection."""
        stations: set[str] = set()
        reply = requests.request("STA-FIRST")
        while reply.strip() and len(stations) < STATION_LIMIT:
            mac = reply.splitlines()[0].strip().lower()
            if mac in stations or mac.startswith("fail"):
                break
            stations.add(mac)
            reply = requests.request(f"STA-NEXT {mac}")
        return stations

    def _listen(self) -> None:
        events = self._events
        if events is None:
            return
        try:
            message = events.receive(PING_INTERVAL)
        except ControlError as exc:
            with self._lock:
                self._lose(str(exc))
            return
        if message is not None:
            self._handle(message)
            return
        # Quiet for PING_INTERVAL: is hostapd still there? Asked on the request
        # socket, so no event is skipped while waiting for the reply.
        try:
            reply = self.request("PING", PING_TIMEOUT)   # marks the connection lost on failure
        except ControlError:
            return
        if reply.strip() != "PONG":
            with self._lock:
                self._lose(f"unexpected PING reply {reply.strip()[:20]!r}")

    def _handle(self, message: str) -> None:
        text = message.split(">", 1)[1] if message.startswith("<") else message
        words = text.split()
        if not words:
            return
        event = words[0]
        changed = False
        with self._lock:
            if event == "AP-STA-CONNECTED" and len(words) > 1:
                self._stations.add(words[1].lower())
            elif event == "AP-STA-DISCONNECTED" and len(words) > 1:
                self._stations.discard(words[1].lower())
            elif event == "AP-ENABLED":
                self._enabled = True
            elif event in ("AP-DISABLED", "CTRL-EVENT-TERMINATING"):
                self._enabled, changed = False, True
        if changed:
            logger.warning("hostapd on %s reported %s", self.interface, event)
            self._notify()

    def _lose(self, why: str) -> None:
        """Mark the connection lost (caller holds the lock); the thread reconnects."""
        if not self._connected.is_set() or self._closed.is_set():
            self._drop()
            return
        self._drop()
        logger.warning("Control connection to hostapd on %s lost: %s; reconnecting", self.interface, why)
        threading.Thread(target=self._notify, daemon=True).start()   # never call out under the lock

    def _drop(self) -> None:
        self._connected.clear()
        for sock in (self._events, self._requests):
            if sock is not None:
                sock.close()
        self._events = self._requests = None
        self._enabled = None

    def _notify(self) -> None:
        if self._on_change is None or self._closed.is_set():
            return
        try:
            self._on_change()
        except Exception:
            logger.warning("hostapd monitor callback failed on %s", self.interface, exc_info=True)
