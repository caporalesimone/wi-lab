"""ARCH-10: the logging rules of docs/readme-dev.md, and wilab.log.

1. ERROR means someone must act: a start attempt the retry recovers, a cancelled
   start and a busy device log none.
2. A message that repeats for the same cause is written at most once per interval.
3. Logging calls never format their message themselves (ruff G004): checked here
   on every module, so it holds without a ruff configuration.
"""

import ast
import io
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import configured_devices

from wilab import log
from wilab.config import load_config
from wilab.models import NetworkCreateRequest
from wilab.wifi import startup as startup_module
from wilab.wifi.hostapd import HostapdCancelled, HostapdSegfault
from wilab.wifi.manager import NetworkManager, StartupFailure

ROOT = Path(__file__).resolve().parents[2]
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def _logging_calls_with_fstrings(path: Path) -> list[str]:
    found = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in LOG_METHODS:
            continue
        target = node.func.value
        name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        if "log" not in name.lower():
            continue
        index = 1 if node.func.attr == "log" else 0
        if len(node.args) > index and isinstance(node.args[index], ast.JoinedStr):
            found.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def test_no_logging_call_formats_its_own_message():
    """Rule 3 (G004): `logger.x("... %s", value)`, never an f-string."""
    files = [ROOT / "main.py", *sorted((ROOT / "wilab").rglob("*.py"))]
    offenders = [hit for path in files for hit in _logging_calls_with_fstrings(path)]
    assert offenders == []


# ----------------------------------------------------------------------------- wilab.log


@pytest.fixture
def captured():
    stream = io.StringIO()
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    log.setup(stream=stream, journal=True)
    log.reset_throttle()
    yield stream
    root.handlers[:], level = saved
    root.setLevel(level)


def test_journal_lines_carry_their_priority(captured):
    logger = logging.getLogger("wilab.test")
    logger.error("broken")
    logger.warning("odd")
    logger.info("fine")
    lines = captured.getvalue().splitlines()
    assert [line[:3] for line in lines] == ["<3>", "<4>", "<6>"]


def test_context_is_added_without_touching_the_call(captured):
    logger = logging.getLogger("wilab.test")
    with log.context(antenna="wlan0", reservation="1a2b3c4d"):
        logger.info("inside")
        with log.context(reservation="ffff0000"):
            logger.info("nested")
    logger.info("outside")
    lines = captured.getvalue().splitlines()
    assert "[ant=wlan0 res=1a2b3c4d] inside" in lines[0]
    assert "[ant=wlan0 res=ffff0000] nested" in lines[1]
    assert lines[2].endswith(" - INFO - outside")


def _access(method: str, status: int) -> None:
    # The record uvicorn writes for every request: (client, method, path, version, status).
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "192.168.10.100:5000", method, "/api/v2/status", "1.1", status,
    )


def test_at_info_successful_reads_are_not_written(captured):
    """Polling GETs were most of the journal; changes and failures are the record of who did what."""
    for method, status in [("GET", 200), ("HEAD", 200), ("GET", 304), ("POST", 201),
                           ("DELETE", 200), ("PUT", 200), ("GET", 404), ("GET", 500)]:
        _access(method, status)
    lines = captured.getvalue().splitlines()
    written = [line.split('"')[1].split()[0] + " " + line.rsplit(" ", 1)[1] for line in lines]
    assert written == ["POST 201", "DELETE 200", "PUT 200", "GET 404", "GET 500"]
    assert all(line.startswith("<6>") for line in lines)


def test_at_debug_every_request_is_written(captured):
    log.set_level(logging.DEBUG)
    _access("GET", 200)
    _access("POST", 201)
    lines = captured.getvalue().splitlines()
    assert [line[:3] for line in lines] == ["<7>", "<6>"]
    assert " - DEBUG - " in lines[0]


@pytest.mark.parametrize(("level", "written"), [
    ("ERROR", ["<3>"]), ("WARNING", ["<3>", "<4>"]), ("INFO", ["<3>", "<4>", "<6>"]),
    ("DEBUG", ["<3>", "<4>", "<6>", "<7>"]),
])
def test_log_level_of_config_yaml(captured, level, written):
    log.set_level(log.level_of(level))
    logger = logging.getLogger("wilab.test")
    logger.error("e")
    logger.warning("w")
    logger.info("i")
    logger.debug("d")
    _access("POST", 201)  # INFO
    lines = captured.getvalue().splitlines()
    assert [line[:3] for line in lines if "wilab.test" in line] == written
    assert any("uvicorn.access" in line for line in lines) == (level in {"INFO", "DEBUG"})


def test_unknown_level_name_is_refused():
    with pytest.raises(ValueError):
        log.level_of("LOUD")


def test_uvicorn_goes_through_the_same_format(captured):
    logging.getLogger("uvicorn.error").info("served")
    assert " - uvicorn.error - INFO - served" in captured.getvalue()


def test_repeated_message_is_written_once_per_interval(captured, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(log.time, "monotonic", lambda: now[0])
    logger = logging.getLogger("wilab.test")
    for _ in range(5):
        log.every(logger, logging.WARNING, "cause", "same %s", "thing", interval=60)
    log.every(logger, logging.WARNING, "other", "different")
    now[0] += 61
    log.every(logger, logging.WARNING, "cause", "same %s", "thing", interval=60)
    lines = captured.getvalue().splitlines()
    assert len(lines) == 3
    assert lines[0].endswith("same thing")
    assert lines[1].endswith("different")
    assert lines[2].endswith("same thing (4 similar messages in the last 60 s not shown)")


# ----------------------------------------------------------------------------- rule 1


def _request() -> NetworkCreateRequest:
    return NetworkCreateRequest(ssid="rules", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)


@pytest.fixture
def manager(monkeypatch) -> NetworkManager:
    mgr = NetworkManager(load_config(), configured_devices())
    monkeypatch.setattr(startup_module, "STARTUP_RETRY_DELAY", 0.0)
    monkeypatch.setattr(mgr.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(mgr.dhcp_server, "stop", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "stop", Mock())
    monkeypatch.setattr(mgr._channel_manager, "validate_network", Mock())
    return mgr


def _errors(caplog) -> list[str]:
    return [f"{r.name}: {r.getMessage()}" for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_start_the_retry_recovers_logs_no_error(monkeypatch, manager, caplog):
    """The long run: 43 recovered segfaults were 43 ERROR lines with no failure behind them."""
    device = manager.config.antennas[0].device_id
    start = Mock(side_effect=[HostapdSegfault(f"hostapd segfault on {device}"), None])
    monkeypatch.setattr(manager.hostapd_manager, "start", start)
    with caplog.at_level(logging.INFO):
        manager.start_network(device, _request(), allow_internal_retry=True)
    assert start.call_count == 2
    assert _errors(caplog) == []
    assert any("attempt 1/3" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_a_cancelled_start_logs_neither_error_nor_warning(monkeypatch, manager, caplog):
    """The long run: 74 cancels by the user were 74 ERROR lines."""
    device = manager.config.antennas[0].device_id
    monkeypatch.setattr(
        manager.hostapd_manager, "start", Mock(side_effect=HostapdCancelled(f"AP start on {device} cancelled")),
    )
    with caplog.at_level(logging.INFO), pytest.raises(StartupFailure):
        manager.start_network(device, _request(), cancelled=lambda: True)
    startup = [r for r in caplog.records if r.name == "wilab.wifi.startup"]
    assert [r.levelno for r in startup] == [logging.INFO]
    assert "cancelled" in startup[0].getMessage()
