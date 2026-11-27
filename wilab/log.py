"""Logging of the service, configured in one place (ARCH-10).

- `setup()` is the only logging configuration: format, levels, and the loggers
  of uvicorn and httpx. Under systemd every line starts with its syslog
  priority (`<3>` for ERROR), so `journalctl -u wi-lab -p err` shows exactly
  the ERROR records.
- `context(antenna=..., reservation=...)` adds the antenna and the reservation
  of the operation running to every record written inside it, without
  changing the calls: `journalctl -u wi-lab | grep res=1a2b3c4d` follows one
  reservation. Threads start with an empty context, so a background thread
  binds its own (`bind`).
- `every()` writes a message that can repeat for the same cause at most once
  per interval, with the count of the ones it held back.

The rules on levels (docs/readme-dev.md, checked by test_logging_rules.py):
ERROR means someone must act; a failed attempt that is retried, or an expected
answer of a check, is a WARNING or less; what a user asked for (a cancel, a
release) is INFO.
"""

from __future__ import annotations

import contextvars
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO

_antenna: contextvars.ContextVar[str | None] = contextvars.ContextVar("wilab_antenna", default=None)
_reservation: contextvars.ContextVar[str | None] = contextvars.ContextVar("wilab_reservation", default=None)

FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(context)s%(message)s"
# sd-daemon(3) priority prefixes, read by journald on the service's stderr.
_SYSLOG_PRIORITY = {
    logging.CRITICAL: 2, logging.ERROR: 3, logging.WARNING: 4, logging.INFO: 6, logging.DEBUG: 7,
}
# Libraries whose own handlers would bypass this format, and their level.
_LIBRARIES = {
    "uvicorn": logging.INFO, "uvicorn.error": logging.INFO, "uvicorn.access": logging.INFO,
    "httpx": logging.WARNING, "httpcore": logging.WARNING,
}


class ContextFilter(logging.Filter):
    """Adds `context` ("[ant=wlx0 res=1a2b3c4d] " or "") and `syslog_priority` to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        antenna = _antenna.get()
        reservation = _reservation.get()
        parts = []
        if antenna:
            parts.append(f"ant={antenna}")
        if reservation:
            parts.append(f"res={reservation}")
        record.context = f"[{' '.join(parts)}] " if parts else ""
        record.syslog_priority = _SYSLOG_PRIORITY.get(record.levelno, 6)
        return True


def under_journal() -> bool:
    """True when stderr is connected to the journal (systemd sets JOURNAL_STREAM)."""
    return bool(os.environ.get("JOURNAL_STREAM"))


# Requests that only read: when they succeed they are written at DEBUG.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class AccessFilter(logging.Filter):
    """Writes the successful reads of uvicorn's access log at DEBUG.

    Clients poll `GET /status` and `GET .../network` every few seconds: at INFO
    those lines were most of the journal and said nothing. What changes
    something (POST, PUT, DELETE) and every answer of 400 or more stay INFO:
    they are the record of who did what.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn's access record: (client, method, path, http_version, status).
        if isinstance(args, tuple) and len(args) == 5:
            method, status = args[1], args[4]
            if method in _READ_METHODS and isinstance(status, int) and status < 400:
                record.levelno, record.levelname = logging.DEBUG, "DEBUG"
        return True


def level_of(name: str) -> int:
    """The `logging` level of a `log_level` name of config.yaml (DEBUG, INFO, WARNING, ERROR)."""
    level = logging.getLevelName(name.upper())
    if not isinstance(level, int):
        raise ValueError(f"unknown log level: {name}")
    return level


def set_level(level: int) -> None:
    """Change the level of the service log (`log_level` of config.yaml) after `setup()`."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)


def setup(level: int = logging.INFO, stream: IO[str] | None = None, *, journal: bool | None = None) -> None:
    """Configure logging for the whole process; safe to call again (tests).

    The level is also the handler's: records of the libraries (uvicorn) and the
    access lines moved to DEBUG pass through it too.
    """
    journal = under_journal() if journal is None else journal
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(level)
    handler.addFilter(ContextFilter())
    handler.setFormatter(logging.Formatter(("<%(syslog_priority)d>" if journal else "") + FORMAT))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name, library_level in _LIBRARIES.items():
        library = logging.getLogger(name)
        library.handlers.clear()
        library.propagate = True
        library.setLevel(library_level)
        library.filters[:] = [f for f in library.filters if not isinstance(f, AccessFilter)]
    logging.getLogger("uvicorn.access").addFilter(AccessFilter())


@contextmanager
def context(*, antenna: str | None = None, reservation: str | None = None) -> Iterator[None]:
    """Records written inside carry *antenna* and *reservation* (None keeps the outer value)."""
    tokens = []
    if antenna is not None:
        tokens.append((_antenna, _antenna.set(antenna)))
    if reservation is not None:
        tokens.append((_reservation, _reservation.set(reservation)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def bind(*, antenna: str | None = None, reservation: str | None = None) -> None:
    """Set the context for the rest of the current thread (a thread owned by one antenna)."""
    if antenna is not None:
        _antenna.set(antenna)
    if reservation is not None:
        _reservation.set(reservation)


def current() -> tuple[str | None, str | None]:
    """The antenna and reservation of the current context."""
    return _antenna.get(), _reservation.get()


class _Throttle:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[tuple[str, object], float] = {}
        self._held: dict[tuple[str, object], int] = {}

    def due(self, key: tuple[str, object], interval: float) -> int | None:
        """None to hold the message back, else how many were held back since the last one."""
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < interval:
                self._held[key] = self._held.get(key, 0) + 1
                return None
            self._last[key] = now
            return self._held.pop(key, 0)

    def clear(self) -> None:
        with self._lock:
            self._last.clear()
            self._held.clear()


_throttle = _Throttle()


def every(
    logger: logging.Logger, level: int, key: object, message: str, *args: object,
    interval: float = 60.0,
) -> None:
    """Log *message* at most once per *interval* seconds for (*logger*, *key*) (rule 2)."""
    held = _throttle.due((logger.name, key), interval)
    if held is None:
        return
    if held:
        logger.log(level, message + " (%d similar messages in the last %.0f s not shown)", *args, held, interval)
    else:
        logger.log(level, message, *args)


def reset_throttle() -> None:
    """Forget the messages seen so far (tests)."""
    _throttle.clear()
