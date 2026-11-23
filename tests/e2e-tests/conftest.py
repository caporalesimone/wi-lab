"""End-to-end tests against a running Wi-Lab service on real hardware.

These tests combine API calls with actions on the server (sysfs, journal,
`iw`). They run on the Wi-Lab machine itself and are skipped unless
WILAB_E2E=1. See docs/e2e-testing.md.

Environment:
    WILAB_E2E=1               enable the suite
    WILAB_E2E_URL             API base URL (default http://localhost:8080)
    WILAB_E2E_TOKEN           bearer token (default: auth_token in WILAB_E2E_CONFIG)
    WILAB_E2E_CONFIG          service config (default: <repo>/config.yaml)
    WILAB_E2E_SUDO_FILE       file with the sudo password (default ~/.wilabsudo)
    WILAB_E2E_USB=1           allow simulated USB unplugs (sysfs `authorized`)
    WILAB_E2E_USB_ACTIVE_AP=1 also allow unplugs while an AP is running
    WILAB_E2E_SLOW=1          allow tests that take more than a few minutes
    WILAB_E2E_CYCLES          create/delete cycles per antenna (default 10)
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from wilab_e2e import Server, WiLab

REPO_ROOT = Path(__file__).resolve().parents[2]

# (marker, environment flag, skip reason); checked in this order.
_GATES = [
    ("e2e", "WILAB_E2E", "end-to-end tests need WILAB_E2E=1 and a running service"),
    ("usb", "WILAB_E2E_USB", "simulated USB unplug needs WILAB_E2E_USB=1"),
    ("usb_active_ap", "WILAB_E2E_USB_ACTIVE_AP", "unplug with an active AP needs WILAB_E2E_USB_ACTIVE_AP=1"),
    ("slow", "WILAB_E2E_SLOW", "long test needs WILAB_E2E_SLOW=1"),
    ("service_restart", "WILAB_E2E_RESTART", "killing and restarting the service needs WILAB_E2E_RESTART=1"),
]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Collection hooks see every item of the session: only gate the ones in this folder.
    here = Path(__file__).parent
    for item in items:
        if here not in Path(str(item.fspath)).parents:
            continue
        item.add_marker(pytest.mark.e2e)
        for marker, env, reason in _GATES:
            if item.get_closest_marker(marker) and os.environ.get(env) != "1":
                item.add_marker(pytest.mark.skip(reason=reason))
                break


@pytest.fixture(scope="session")
def server() -> Iterator[Server]:
    srv = Server(Path(os.environ.get("WILAB_E2E_SUDO_FILE", str(Path.home() / ".wilabsudo"))))
    yield srv
    # Never leave an antenna unplugged, whatever happened in the test.
    for port in list(srv.unplugged):
        srv.set_usb_authorized(port, 1)


@pytest.fixture(scope="session")
def _token() -> str:
    token = os.environ.get("WILAB_E2E_TOKEN")
    if token:
        return token
    config = Path(os.environ.get("WILAB_E2E_CONFIG", str(REPO_ROOT / "config.yaml")))
    return str(yaml.safe_load(config.read_text())["auth_token"])


@pytest.fixture
def wilab(_token: str) -> Iterator[WiLab]:
    """API client; skips when another run holds an antenna or an antenna is unhealthy."""
    client = WiLab(os.environ.get("WILAB_E2E_URL", "http://localhost:8080"), _token)
    status = client.status()
    busy = [entry["display_name"] for entry in status["networks"] if entry.get("reserved")]
    unhealthy = [
        entry["display_name"] for entry in status["networks"]
        if entry.get("recovery_state") or entry.get("runtime_state")
    ]
    if busy or unhealthy:
        client.close()
        pytest.skip(f"Service not idle (reserved: {busy}, unhealthy: {unhealthy})")
    yield client
    client.close()


@pytest.fixture
def first_interface(wilab: WiLab) -> str:
    return wilab.interfaces()[0]
