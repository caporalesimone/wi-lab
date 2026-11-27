"""Every error code the API can answer is documented in docs/error-codes.md (API-3)."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from wilab.api.errors import ApiErrorCode
from wilab.api.routes.status import REASON_MESSAGES

DOC = (Path(__file__).resolve().parents[2] / "docs" / "error-codes.md").read_text()


def test_every_domain_code_is_documented_with_its_reason():
    for code in ApiErrorCode:
        assert f"| {code.value} | `{code.name.lower()}` |" in DOC, code


def test_every_degraded_reason_is_documented():
    for code in REASON_MESSAGES:
        assert f"| `{code}` |" in DOC, code


def test_codes_are_unique():
    values = [code.value for code in ApiErrorCode]
    assert len(values) == len(set(values))


# --------------------------------------------------------------------------- REV-11 (unit-test-8)


def _operations_with_a_reservation_id(client):
    """(method, path) of every operation on a `{reservation_id}` path, from the published schema."""
    spec = client.get("/openapi.json").json()
    return [
        (method.upper(), path)
        for path, item in spec["paths"].items() if "{reservation_id}" in path
        for method in item if method in ("get", "post", "put", "patch", "delete")
    ]


def test_every_operation_with_a_reservation_id_answers_404_with_the_exact_reason(context, app):
    """unit-test-8: released, expired (before and after the cleanup), invalidated and unknown IDs."""
    config = context.config
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(app) as client:
        operations = _operations_with_a_reservation_id(client)
        # The paths the review found uncovered must be in the list, or it is derived wrongly
        # (there is no plain `/qos` operation on a reservation any more, only `/qos/profile`).
        paths = {path.removeprefix("/api/v2/reservations/{reservation_id}") for _, path in operations}
        assert {"/internet/disable", "/txpower", "/qos/profile"} <= paths
        assert ("POST", "/api/v2/reservations/{reservation_id}/txpower") in operations
        reservations = context.reservations

        def reserve():
            resp = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 300})
            assert resp.status_code == 200, resp.text
            return resp.json()["reservation_id"]

        released = reserve()
        assert client.delete(f"/api/v2/reservations/{released}", headers=headers).status_code == 200
        invalidated = reserve()
        reservations.quarantine(reservations.get(invalidated), recovering=False)
        reservations.finish_recovery(context.manager.config.antennas[0].device_id,
                                     recovered=True)   # the antenna is needed again below

        def answer(method, path, rid):
            resp = client.request(method, path.replace("{reservation_id}", rid), headers=headers, json={})
            assert resp.status_code == 404, (method, path, resp.status_code, resp.text)
            return resp.json()["detail"]["reason"]

        for method, path in operations:
            # An expired ID that no call has cleaned up yet, then the same ID after the cleanup.
            expired = reserve()
            reservations.get(expired).expires_at = time.time() - 1
            assert answer(method, path, expired) == "reservation_expired", (method, path)
            assert not reservations.snapshot(), "the first call did not clean up the expired ID"
            assert answer(method, path, expired) == "reservation_expired", (method, path)
            assert answer(method, path, released) == "reservation_released", (method, path)
            assert answer(method, path, invalidated) == "reservation_invalidated", (method, path)
            assert answer(method, path, "deadbeef") == "reservation_not_found", (method, path)

