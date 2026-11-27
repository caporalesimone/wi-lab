"""Liveness of the background loops and the systemd watchdog (STAB-1).

Each background loop calls `beat(name)` once per iteration. A dedicated
thread sends `WATCHDOG=1` to systemd every `NOTIFY_INTERVAL` seconds unless
a loop has not beaten for `STALE_AFTER` seconds *and* Wi-Lab is idle (no
reservation, no USB recovery running). Only then does it stop, so systemd
(`WatchdogSec`) restarts the service: a hang inside Wi-Lab costs nobody a
network. While a reservation exists the service keeps running, reports the
stale loops in `GET /status` (`checks.loops`, and `service.health` is `degraded`) and restarts as
soon as it is idle.

A command stuck in the kernel (`checks.commands.stuck`) does not trigger a
restart: a new process would hang on the same kernel lock.
"""

import logging
import os
import socket
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

NOTIFY_INTERVAL = 20.0
# Longer than any single loop iteration may legitimately take: a device lock is
# held up to 75 s during a DFS start, and the expiry loop waits for it.
STALE_AFTER = 180.0

_beats: dict[str, float] = {}
_beats_lock = threading.Lock()


def beat(name: str) -> None:
    """Record that loop `name` completed an iteration."""
    with _beats_lock:
        _beats[name] = time.monotonic()


def forget(name: str) -> None:
    """Stop tracking a loop that ended on purpose."""
    with _beats_lock:
        _beats.pop(name, None)


def stale_loops(max_age: float = STALE_AFTER) -> list[str]:
    """Loops that have not completed an iteration for `max_age` seconds."""
    now = time.monotonic()
    with _beats_lock:
        return sorted(name for name, at in _beats.items() if now - at > max_age)


def sd_notify(state: str) -> bool:
    """Send a state line to systemd. False when not started by systemd (no NOTIFY_SOCKET)."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(state.encode())
    except OSError as exc:
        logger.warning("Could not notify systemd (%s): %s", state.split("=")[0], exc)
        return False
    return True


def watchdog_enabled() -> bool:
    """True when systemd expects WATCHDOG=1 pings from this process."""
    return bool(os.environ.get("WATCHDOG_USEC")) and os.environ.get("WATCHDOG_PID", str(os.getpid())) == str(
        os.getpid()
    )


def should_ping(is_idle: Callable[[], bool]) -> tuple[bool, list[str]]:
    """Whether to send WATCHDOG=1 now, and the stale loops (for logging)."""
    stale = stale_loops()
    if not stale:
        return True, stale
    try:
        idle = is_idle()
    except Exception:  # never let a broken check restart a busy service
        logger.exception("Could not tell whether Wi-Lab is idle; keeping the service running")
        return True, stale
    return not idle, stale


def notify_loop(stop: threading.Event, is_idle: Callable[[], bool]) -> None:
    """Ping the systemd watchdog until `stop` is set; see the module docstring."""
    reported: tuple[str, ...] = ()
    while True:
        ping, stale = should_ping(is_idle)
        if tuple(stale) != reported:
            reported = tuple(stale)
            if stale and ping:
                logger.error(
                    "Background loops stalled (%s); restart deferred while reservations exist",
                    ", ".join(stale),
                )
            elif stale:
                logger.critical(
                    "Background loops stalled (%s) and no reservation is active; "
                    "letting systemd restart Wi-Lab",
                    ", ".join(stale),
                )
            else:
                logger.warning("Background loops running again")
        if ping:
            sd_notify("WATCHDOG=1")
        if stop.wait(NOTIFY_INTERVAL):
            return
