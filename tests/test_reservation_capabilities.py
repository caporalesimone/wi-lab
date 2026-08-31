"""Capability-based device selection, at the manager and API levels.

Kept out of test_reservation.py, which is already long and covers the lifecycle rather
than the allocation policy.

Covers TODOs/device-capabilities.md §12.5 and §12.6.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from wilab.api import create_app, dependencies
from wilab.config import Capability, load_config
from wilab.reservation import (
    CapabilityUnsatisfiableError,
    DeviceSpec,
    NoDeviceAvailableError,
    ReservationManager,
    UnknownDeviceError,
)

C24 = Capability.BAND_24GHZ
C5 = Capability.BAND_5GHZ


def _pool(*specs):
    """Build a pool from (device_id, capabilities) pairs, in declaration order."""
    return [
        DeviceSpec(device_id=did, capabilities=frozenset(caps), index=i)
        for i, (did, caps) in enumerate(specs)
    ]


# The worked example from the proposal: one 2.4-only device and two dual-band ones.
STANDARD_POOL = (
    ("only24", {C24}),
    ("dual_a", {C24, C5}),
    ("dual_b", {C24, C5}),
)


@pytest.fixture
def client():
    dependencies._config = None
    dependencies._manager = None
    dependencies._reservation_manager = None
    load_config()
    return TestClient(create_app())


@pytest.fixture
def token():
    return f"Bearer {load_config().auth_token}"


def reserve(client, token, **body):
    body.setdefault("duration_seconds", 60)
    return client.post(
        "/api/v1/device-reservation",
        headers={"Authorization": token},
        json=body,
    )


# ==================================================================================================
# Manager-level selection
# ==================================================================================================


class TestSelectionRules:
    """Table-driven, so a new capability adds rows rather than test functions."""

    @pytest.mark.parametrize("required,expected", [
        pytest.param(set(), "only24", id="no-requirement-takes-the-least-capable"),
        pytest.param({C24}, "only24", id="2.4-prefers-the-2.4-only-device"),
        pytest.param({C5}, "dual_a", id="5ghz-skips-the-2.4-only-device"),
        pytest.param({C24, C5}, "dual_a", id="both-needs-a-dual-band-device"),
    ])
    def test_selection(self, required, expected):
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        assert mgr.create(60, required_capabilities=required).device_id == expected

    def test_minimality_is_a_preference_not_a_filter(self):
        """With the minimal device busy, an over-capable one is used rather than refused."""
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        mgr.create(60, required_capabilities={C24})          # takes only24
        assert mgr.create(60, required_capabilities={C24}).device_id == "dual_a"

    def test_declaration_order_breaks_ties(self):
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        assert mgr.create(60, required_capabilities={C5}).device_id == "dual_a"
        assert mgr.create(60, required_capabilities={C5}).device_id == "dual_b"

    def test_tie_break_is_stable_across_cycles(self):
        """Reproducibility: the same free pool must always hand out the same device."""
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        for _ in range(20):
            r = mgr.create(60, required_capabilities={C5})
            assert r.device_id == "dual_a"
            mgr.delete(r.reservation_id)

    def test_most_capable_first_still_yields_the_minimal_device(self):
        """The pool order where the new rule differs from the old first-free one.

        With [dual, 2.4-only] the previous implementation returned the dual-band adapter
        for an unqualified request; minimality returns the 2.4-only one, leaving the
        scarce hardware free. This is the intentional behaviour change of §11.2.
        """
        mgr = ReservationManager(_pool(("dual", {C24, C5}), ("only24", {C24})))
        assert mgr.create(60).device_id == "only24"

    def test_capability_less_pool_behaves_as_before(self):
        """Legacy construction from plain strings: first free, declaration order."""
        mgr = ReservationManager(["dev0", "dev1"])
        assert mgr.create(60).device_id == "dev0"
        assert mgr.create(60).device_id == "dev1"

    def test_mixed_sequence_is_accepted(self):
        mgr = ReservationManager([DeviceSpec("a", frozenset({C24}), 0), "b"])
        assert {d.device_id for d in mgr._devices} == {"a", "b"}


class TestCapacityVersusImpossibility:
    """The 409/422 distinction: "works later" versus "never works"."""

    def test_all_matching_busy_raises_no_device_available(self):
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        mgr.create(3600, required_capabilities={C5})
        mgr.create(3600, required_capabilities={C5})
        with pytest.raises(NoDeviceAvailableError):
            mgr.create(60, required_capabilities={C5})

    def test_eta_ignores_devices_that_could_never_serve_the_request(self):
        """A 2.4-only antenna freeing up in 30s is no use to a 5 GHz request."""
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        mgr.create(30, required_capabilities={C24})      # only24, frees up first
        mgr.create(3600, required_capabilities={C5})     # dual_a
        mgr.create(3600, required_capabilities={C5})     # dual_b
        with pytest.raises(NoDeviceAvailableError) as exc_info:
            mgr.create(60, required_capabilities={C5})
        assert exc_info.value.next_available_in > 60, (
            "the ETA must come from the dual-band devices, not the 2.4-only one"
        )

    def test_unsatisfiable_set_is_permanent(self):
        """No configured device provides it, so waiting cannot help."""
        mgr = ReservationManager(_pool(("only24", {C24}), ("also24", {C24})))
        with pytest.raises(CapabilityUnsatisfiableError) as exc_info:
            mgr.create(60, required_capabilities={C5})
        assert exc_info.value.available == ["2.4ghz"]

    def test_a_busy_pool_is_capacity_not_impossibility(self):
        """available is computed over the whole pool, which is what makes 422 permanent."""
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        for _ in range(3):
            mgr.create(3600)
        with pytest.raises(NoDeviceAvailableError):
            mgr.create(60, required_capabilities={C5})


class TestPinnedDevice:
    def test_pinning_a_free_device_succeeds(self):
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        assert mgr.create(60, device_id="dual_b").device_id == "dual_b"

    def test_pinning_overrides_minimality(self):
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        assert mgr.create(60, device_id="dual_a").device_id == "dual_a"

    def test_unknown_device(self):
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        with pytest.raises(UnknownDeviceError):
            mgr.create(60, device_id="not-a-device")

    def test_pinned_device_lacking_a_capability(self):
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        with pytest.raises(CapabilityUnsatisfiableError) as exc_info:
            mgr.create(60, required_capabilities={C5}, device_id="only24")
        assert exc_info.value.device_id == "only24"
        assert exc_info.value.missing == frozenset({C5})

    def test_pinned_device_with_satisfied_capabilities(self):
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        assert mgr.create(60, required_capabilities={C24}, device_id="dual_a").device_id == "dual_a"

    def test_pinned_busy_device_reports_its_own_eta(self):
        """Not the pool's soonest: the caller pinned this device and wants its expiry."""
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        mgr.create(30, device_id="only24")     # frees up sooner
        mgr.create(3600, device_id="dual_a")
        with pytest.raises(NoDeviceAvailableError) as exc_info:
            mgr.create(60, device_id="dual_a")
        assert exc_info.value.next_available_in > 60


class TestCapabilityConcurrency:
    def test_no_double_assignment_under_contention(self):
        """Threads racing for the same capability must never share a device."""
        mgr = ReservationManager(_pool(*STANDARD_POOL))
        granted, errors = [], []
        lock = threading.Lock()

        def worker():
            try:
                r = mgr.create(60, required_capabilities={C5})
                with lock:
                    granted.append(r.device_id)
            except (NoDeviceAvailableError, CapabilityUnsatisfiableError) as exc:
                with lock:
                    errors.append(type(exc).__name__)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(granted) == ["dual_a", "dual_b"], "each device granted exactly once"
        assert len(errors) == 10

    def test_large_pool_drains_without_double_assignment(self):
        """Guard against an accidental quadratic or lossy scan as the pool grows."""
        mgr = ReservationManager(_pool(*[(f"dev{i}", {C24}) for i in range(200)]))
        granted = {mgr.create(60, required_capabilities={C24}).device_id for _ in range(200)}
        assert len(granted) == 200
        with pytest.raises(NoDeviceAvailableError):
            mgr.create(60, required_capabilities={C24})


# ==================================================================================================
# API level
# ==================================================================================================
#
# The shared fixture declares:
#   wls16  bench-antenna-1  2.4ghz + 5ghz
#   wls17  bench-antenna-2  2.4ghz only
#   wls18  bench-antenna-3  2.4ghz + 5ghz


class TestStatusCapabilities:
    def test_networks_expose_enabled_capabilities_only(self, client, token):
        data = client.get("/api/v1/status", headers={"Authorization": token}).json()
        by_iface = {n["interface"]: n["capabilities"] for n in data["networks"]}
        assert by_iface["wls16"] == ["2.4ghz", "5ghz"]
        assert by_iface["wls17"] == ["2.4ghz"], "a false capability must not reach the wire"

    def test_capabilities_are_sorted(self, client, token):
        data = client.get("/api/v1/status", headers={"Authorization": token}).json()
        for n in data["networks"]:
            assert n["capabilities"] == sorted(n["capabilities"])

    def test_catalogue_carries_label_kind_and_counts(self, client, token):
        data = client.get("/api/v1/status", headers={"Authorization": token}).json()
        catalogue = {c["id"]: c for c in data["capabilities_catalogue"]}
        assert catalogue["2.4ghz"]["label"] == "2.4 GHz"
        assert catalogue["5ghz"]["kind"] == "radio"
        assert catalogue["2.4ghz"]["total_devices"] == 3
        assert catalogue["5ghz"]["total_devices"] == 2

    def test_available_counts_track_reservations(self, client, token):
        def counts():
            data = client.get("/api/v1/status", headers={"Authorization": token}).json()
            return {c["id"]: c["available_devices"] for c in data["capabilities_catalogue"]}

        assert counts() == {"2.4ghz": 3, "5ghz": 2}
        rid = reserve(client, token, required_capabilities=["5ghz"]).json()["reservation_id"]
        assert counts() == {"2.4ghz": 2, "5ghz": 1}
        client.delete(f"/api/v1/device-reservation/{rid}", headers={"Authorization": token})
        assert counts() == {"2.4ghz": 3, "5ghz": 2}

    def test_debug_reports_capabilities_too(self, client, token):
        data = client.get("/api/v1/debug", headers={"Authorization": token}).json()
        managed = {m["interface"]: m["capabilities"] for m in data["interfaces"]["managed"]}
        assert managed["wls17"] == ["2.4ghz"]


class TestReservationApiSelection:
    def test_capability_request_gets_the_minimal_device(self, client, token):
        body = reserve(client, token, required_capabilities=["2.4ghz"]).json()
        assert body["interface"] == "wls17"
        assert body["capabilities"] == ["2.4ghz"]

    def test_five_ghz_request_gets_a_dual_band_device(self, client, token):
        body = reserve(client, token, required_capabilities=["5ghz"]).json()
        assert body["interface"] == "wls16"
        assert body["capabilities"] == ["2.4ghz", "5ghz"]

    def test_legacy_body_still_works(self, client, token):
        resp = reserve(client, token)
        assert resp.status_code == 200
        assert resp.json()["capabilities"]

    def test_empty_list_behaves_like_omitting_the_field(self, client, token):
        with_empty = reserve(client, token, required_capabilities=[]).json()["interface"]
        client.delete("/api/v1/device-reservation", headers={"Authorization": token})
        without = reserve(client, token).json()["interface"]
        assert with_empty == without

    def test_ids_are_case_insensitive_and_de_duplicated(self, client, token):
        resp = reserve(client, token, required_capabilities=["5GHz", " 5ghz ", "5ghz"])
        assert resp.status_code == 200
        assert resp.json()["interface"] == "wls16"

    def test_get_reservation_echoes_capabilities(self, client, token):
        rid = reserve(client, token, required_capabilities=["5ghz"]).json()["reservation_id"]
        got = client.get(
            f"/api/v1/device-reservation/{rid}", headers={"Authorization": token}
        ).json()
        assert got["capabilities"] == ["2.4ghz", "5ghz"]


class TestReservationApiErrors:
    def test_unknown_capability_is_422_listing_the_valid_ids(self, client, token):
        resp = reserve(client, token, required_capabilities=["6ghz"])
        assert resp.status_code == 422
        assert "5ghz" in str(resp.json())

    def test_all_matching_busy_is_409(self, client, token):
        reserve(client, token, required_capabilities=["5ghz"], duration_seconds=3600)
        reserve(client, token, required_capabilities=["5ghz"], duration_seconds=3600)
        resp = reserve(client, token, required_capabilities=["5ghz"])
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["requested_capabilities"] == ["5ghz"]
        assert detail["next_available_in"] > 0

    def test_409_eta_ignores_the_unusable_device(self, client, token):
        """wls17 frees up first but can never serve 5 GHz."""
        reserve(client, token, required_capabilities=["2.4ghz"], duration_seconds=60)
        reserve(client, token, required_capabilities=["5ghz"], duration_seconds=3600)
        reserve(client, token, required_capabilities=["5ghz"], duration_seconds=3600)
        detail = reserve(client, token, required_capabilities=["5ghz"]).json()["detail"]
        assert detail["next_available_in"] > 60

    def test_pinned_interface_succeeds(self, client, token):
        body = reserve(client, token, interface="wls18").json()
        assert body["interface"] == "wls18"

    def test_unknown_interface_is_404(self, client, token):
        """404, not 422, so a client can tell 'no such device' from 'cannot serve you'."""
        resp = reserve(client, token, interface="wlan99")
        assert resp.status_code == 404
        assert "wlan99" in resp.json()["detail"]

    def test_pinned_busy_interface_is_409(self, client, token):
        reserve(client, token, interface="wls18", duration_seconds=3600)
        resp = reserve(client, token, interface="wls18")
        assert resp.status_code == 409

    def test_pinned_interface_lacking_the_capability_is_422(self, client, token):
        resp = reserve(client, token, interface="wls17", required_capabilities=["5ghz"])
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["interface"] == "wls17"
        assert detail["missing"] == ["5ghz"]

    def test_pinned_interface_with_satisfied_capability(self, client, token):
        resp = reserve(client, token, interface="wls16", required_capabilities=["5ghz"])
        assert resp.status_code == 200


class TestOpenApiCompatibility:
    def test_schema_still_generates_and_new_fields_are_optional(self, client):
        schema = client.get("/openapi.json").json()
        body = schema["components"]["schemas"]["ReservationCreateRequest"]
        assert body["required"] == ["duration_seconds"], (
            "the new request fields must stay optional; existing clients send neither"
        )
        assert "required_capabilities" in body["properties"]
        assert "interface" in body["properties"]
