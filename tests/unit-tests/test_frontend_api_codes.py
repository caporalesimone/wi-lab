"""The frontend handles the API codes 1006 (device busy) and 1007 (network not active)."""

from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "frontend/src/app"


def test_codes_and_hints_are_defined():
    recovery = (APP / "services/recovery-response.ts").read_text()
    assert "DeviceBusy = 1006" in recovery and "NetworkNotActive = 1007" in recovery
    assert "[RecoveryCode.DeviceBusy]:" in recovery and "[RecoveryCode.NetworkNotActive]:" in recovery
    assert "retryAfterSeconds(error, 503, RecoveryCode.DeviceBusy)" in recovery


def test_busy_answers_are_retried_on_every_reservation_call_but_the_create():
    service = (APP / "services/wilab-api.service.ts").read_text()
    for method in ("getNetworkStatus", "stopNetwork", "enableInternet", "disableInternet"):
        body = service.split(f"public {method}(", 1)[1].split("\n  public ", 1)[0]
        assert "retryWhenBusy()" in body, method
    create = service.split("public startNetwork(", 1)[1].split("\n  public ", 1)[0]
    assert "retryWhenBusy" not in create  # the create waits on the server instead


def test_quarantine_is_detected_by_code_not_status():
    card = (APP / "components/network-card/network-card.component.ts").read_text()
    assert "raw?.status === 500" not in card
    assert "detail?.code === RecoveryCode.DeviceUnavailable" in card
