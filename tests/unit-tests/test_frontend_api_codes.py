"""The frontend handles the API codes 1006 (device busy) and 1007 (network not active)."""

from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "frontend/src/app"


def test_codes_and_hints_are_defined():
    recovery = (APP / "services/recovery-response.ts").read_text()
    assert "DeviceBusy = 1006" in recovery and "NetworkNotActive = 1007" in recovery
    assert "[RecoveryCode.DeviceBusy]:" in recovery and "[RecoveryCode.NetworkNotActive]:" in recovery
    assert "codes: RecoveryCode[] = [RecoveryCode.DeviceBusy]" in recovery
    assert "retryAfterSeconds(error, 503, code)" in recovery


def test_busy_answers_are_retried_on_every_reservation_call_but_the_create():
    service = (APP / "services/wilab-api.service.ts").read_text()
    for method in ("getNetworkStatus", "enableInternet", "disableInternet"):
        body = service.split(f"public {method}(", 1)[1].split("\n  public ", 1)[0]
        assert "retryWhenBusy()" in body, method
    stop = service.split("public stopNetwork(", 1)[1].split("\n  public ", 1)[0]
    # The stop also repeats 503 / 1012 (stop_incomplete) after Retry-After.
    assert "retryWhenBusy(4, [RecoveryCode.DeviceBusy, RecoveryCode.StopIncomplete])" in stop
    create = service.split("public startNetwork(", 1)[1].split("\n  public ", 1)[0]
    # Only 1006 is repeated: the same body on a running network reads it like GET (REV-11).
    assert "retryWhenBusy()" in create
    assert "retry(" not in create  # radio failures are retried by the server (no 409 / 1001)


def test_create_polls_and_quarantine_is_detected_by_reason():
    """Asynchronous create: the card reads start_failed and the 404 reason, not a status code."""
    service = (APP / "services/wilab-api.service.ts").read_text()
    create = service.split("public startNetwork(", 1)[1].split("\n  public ", 1)[0]
    assert "runtime_state !== 'starting'" in create and "timer(" in create
    card = (APP / "components/network-card/network-card.component.ts").read_text()
    assert "runtime_state === 'start_failed'" in card
    # Every 404 reason becomes a sentence (REV-13), invalidated included.
    assert "reservationGoneText(err)" in card
    recovery = (APP / "services/recovery-response.ts").read_text()
    assert "reservation_invalidated:" in recovery
