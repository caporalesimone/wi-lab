"""Long-run stress tests against a running Wi-Lab service on real hardware.

They create networks continuously through the API for a fixed time and then
check that nothing is left behind. Skipped unless WILAB_LONG_RUN=1.

Environment:
    WILAB_LONG_RUN=1          enable the suite
    WILAB_LONG_MINUTES        total duration of the suite in minutes (default 120);
                              each test gets its share (see WEIGHTS in stress.py)
    WILAB_LONG_SEED           seed of the random choices (default: time-based, printed)
    WILAB_E2E_URL, WILAB_E2E_TOKEN, WILAB_E2E_CONFIG, WILAB_E2E_SUDO_FILE
                              as in tests/e2e-tests (same helpers); the burst test's
                              chaos monkey kills hostapd and dnsmasq with sudo

Run:  WILAB_LONG_RUN=1 .venv/bin/pytest tests/long-run -s
The events of every run are written to tests/long-run/results/ (git-ignored).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests" / "e2e-tests"))   # reuse the e2e helpers

from wilab_e2e import Server, WiLab


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("WILAB_LONG_RUN") == "1":
        return
    for item in items:
        if HERE in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.skip(reason="long-run stress tests need WILAB_LONG_RUN=1"))


@pytest.fixture(scope="session")
def server() -> Server:
    return Server(Path(os.environ.get("WILAB_E2E_SUDO_FILE", str(Path.home() / ".wilabsudo"))))


@pytest.fixture(scope="session")
def token() -> str:
    if os.environ.get("WILAB_E2E_TOKEN"):
        return os.environ["WILAB_E2E_TOKEN"]
    config = Path(os.environ.get("WILAB_E2E_CONFIG", str(REPO_ROOT / "config.yaml")))
    return str(yaml.safe_load(config.read_text())["auth_token"])


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("WILAB_E2E_URL", "http://localhost:8080")


@pytest.fixture
def idle(base_url: str, token: str) -> Iterator[WiLab]:
    """A client on an idle service: fails (not skips) when the service is busy or unhealthy."""
    client = WiLab(base_url, token)
    status = client.status()
    busy = [a["display_name"] for a in status["antennas"] if a.get("reservation")]
    unhealthy = [a["display_name"] for a in status["antennas"] if a.get("recovery_state") or a.get("runtime_state")]
    assert not busy and not unhealthy, f"service not idle (reserved: {busy}, unhealthy: {unhealthy})"
    assert len(status["antennas"]) >= 2, "the long run needs two antennas"
    yield client
    client.close()
