"""WD-5 and WD-4 on real hardware: an antenna that disappears and comes back.

The unplug is simulated by writing 0 and then 1 to the USB device's
`authorized` attribute in sysfs. Every test re-authorizes the port at the end
(see the `server` fixture), but a real driver hang can still detach the
device from the VM: see docs/e2e-testing.md before enabling these tests.
"""

import threading
import time
from collections.abc import Iterator

import httpx
import pytest
from wilab_e2e import Server, WiLab, wait_for

pytestmark = pytest.mark.usb


@pytest.fixture(autouse=True)
def _replug_after_the_test(server: Server) -> Iterator[None]:
    """Re-authorize the port when a test fails half way.

    The `server` fixture does it only at the end of the session: the next test
    would otherwise start with the antenna still unplugged.
    """
    yield
    for port in list(server.unplugged):
        server.set_usb_authorized(port, 1)

# USB recovery: 10 attempts 60 s apart. Re-probe backoff tops out at 900 s.
RECOVERY_WINDOW = 11 * 60
REPROBE_WINDOW = 16 * 60


def test_antenna_gone_at_create_is_waited_for_by_the_server(
    wilab: WiLab, server: Server, first_interface: str,
) -> None:
    """WD-5 #1-#2: back during the server's 5 s pause -> one create answers 200, no quarantine."""
    antenna = wilab.reserve(first_interface)
    port = server.usb_port(antenna.interface)
    start = time.time()
    server.set_usb_authorized(port, 0)
    assert server.wait_interface(antenna.interface, present=False)

    result: dict[str, httpx.Response] = {}
    create = threading.Thread(target=lambda: result.update(response=wilab.create(antenna)), daemon=True)
    create.start()
    time.sleep(2)  # the first round has failed; the server is in its 5 s pause
    server.set_usb_authorized(port, 1)
    assert server.wait_interface(antenna.interface)
    create.join(timeout=150)
    assert "response" in result, "the create did not end within 150 s"
    response = result["response"]
    assert response.status_code == 200, response.text
    assert not wilab.device(antenna.interface).get("recovery_state")
    assert "Startup rollback failed" not in server.journal(start)


def test_free_antenna_unplug_and_replug(wilab: WiLab, server: Server, first_interface: str) -> None:
    """WD-5 #5: no quarantine for an unreserved antenna; it works afterwards."""
    port = server.usb_port(first_interface)
    server.set_usb_authorized(port, 0)
    time.sleep(5)
    server.set_usb_authorized(port, 1)
    assert server.wait_interface(first_interface)
    time.sleep(3)
    assert not wilab.device(first_interface).get("recovery_state")
    antenna = wilab.reserve(first_interface)
    assert wilab.create(antenna).status_code == 200


def _quarantine_while_gone(wilab: WiLab, server: Server, interface: str) -> str:
    """Unplug, then let one create fail on every round (pauses 5 s and 10 s); return the USB port."""
    antenna = wilab.reserve(interface)
    port = server.usb_port(interface)
    server.set_usb_authorized(port, 0)
    assert server.wait_interface(interface, present=False)
    started = time.monotonic()
    response = wilab.create(antenna)
    assert response.status_code == 404, response.text  # asynchronous create: the polling ends in 404
    assert response.json()["detail"]["reason"] == "reservation_invalidated"
    assert time.monotonic() - started >= 15  # the server took both pauses itself
    wilab.reserved.remove(antenna.reservation_id)  # invalidated by the quarantine
    # e2e-test-5: the same reason on every call with the ID.
    answers = wilab.gone_answers(antenna.reservation_id)
    assert set(answers.values()) == {(404, "reservation_invalidated")}, answers
    status = wilab.status()
    assert wilab.device(interface)["recovery_state"] == "recovering"
    assert status["service"]["health"] == "degraded"
    return port


def test_antenna_gone_across_three_creates_recovers_by_usb_recovery(
    wilab: WiLab, server: Server, first_interface: str,
) -> None:
    """WD-5 #3-#4: quarantine as "recovering", never "unavailable"; back after replug."""
    start = time.time()
    port = _quarantine_while_gone(wilab, server, first_interface)
    time.sleep(5)
    server.set_usb_authorized(port, 1)
    assert server.wait_interface(first_interface)
    assert wait_for(lambda: not wilab.device(first_interface).get("recovery_state"), timeout=150)
    assert "USB recovery verified" in server.journal(start)
    antenna = wilab.reserve(first_interface)
    assert wilab.create(antenna).status_code == 200


@pytest.mark.usb_active_ap
def test_antenna_gone_with_active_network(wilab: WiLab, server: Server, first_interface: str) -> None:
    """WD-5 #6: the watchdog never leaves the antenna permanently unavailable.

    Risky: on mt7921u in a VM this has stalled the VM and detached the USB
    device (23/11 17:50), which then needs a physical re-plug.
    """
    antenna = wilab.reserve(first_interface)
    assert wilab.create(antenna).status_code == 200
    port = server.usb_port(first_interface)
    start = time.time()
    server.set_usb_authorized(port, 0)
    time.sleep(30)
    server.set_usb_authorized(port, 1)
    assert server.wait_interface(first_interface)

    def settled() -> bool:
        entry = wilab.device(first_interface)
        network = wilab.http.get(f"/access-point/{antenna.reservation_id}").status_code
        restored = network == 200 and not entry.get("runtime_state") and not entry.get("recovery_state")
        return restored or (network == 404 and not entry.get("recovery_state"))

    assert wait_for(settled, timeout=RECOVERY_WINDOW + 60, interval=10)
    assert wilab.device(first_interface).get("recovery_state") != "unavailable"
    assert "Startup rollback failed" not in server.journal(start)


@pytest.mark.slow
def test_unavailable_antenna_is_reprobed_without_restart(
    wilab: WiLab, server: Server, first_interface: str,
) -> None:
    """WD-4: USB recovery exhausts while unplugged, then the re-probe brings it back."""
    start = time.time()
    port = _quarantine_while_gone(wilab, server, first_interface)
    assert wait_for(
        lambda: wilab.device(first_interface).get("recovery_state") == "unavailable",
        timeout=RECOVERY_WINDOW + 60, interval=15,
    )
    assert "USB recovery exhausted" in server.journal(start)
    # The first re-probe comes REPROBE_DELAYS[0] (30 s) after the quarantine, not at once.
    assert wait_for(
        lambda: any(
            line in server.journal(start)
            for line in ("re-probe skipped", "still unavailable after re-probe")
        ),
        timeout=60, interval=5,
    )

    server.set_usb_authorized(port, 1)
    assert server.wait_interface(first_interface)
    assert wait_for(
        lambda: not wilab.device(first_interface).get("recovery_state"), timeout=REPROBE_WINDOW, interval=15,
    )
    assert "passed the probe and is allocatable again" in server.journal(start)
    antenna = wilab.reserve(first_interface)
    assert wilab.create(antenna).status_code == 200
