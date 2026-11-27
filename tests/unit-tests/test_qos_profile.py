"""Tests for QoS Profile system (models, catalogue, manager, API)."""

import json
import os
import threading
import time

import pytest
from conftest import configured_devices, create_network, network_body

from wilab.models import (
    QosProfile,
    QosProfileMode,
    QosProfileStartRequest,
    QosProfileState,
    QosProfileStep,
    QosProfileStepState,
    QosQualityAdvanced,
)
from wilab.network import qos_profile as qos_profile_module
from wilab.network.qos import QosManager
from wilab.network.qos_profile import QosProfileManager

# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------


class TestQosProfileModels:
    """Tests for QoS Profile Pydantic models."""

    def test_step_quality_only(self):
        step = QosProfileStep(duration_sec=10, quality=80)
        assert step.quality == 80
        assert step.advanced is None

    def test_step_advanced_only(self):
        adv = QosQualityAdvanced(delay_ms=100, jitter_ms=20)
        step = QosProfileStep(duration_sec=10, advanced=adv)
        assert step.advanced is not None
        assert step.quality is None

    def test_step_speed_only(self):
        step = QosProfileStep(duration_sec=10, dl_speed_kbit=5000)
        assert step.dl_speed_kbit == 5000

    def test_step_quality_and_speed(self):
        step = QosProfileStep(duration_sec=10, quality=80, dl_speed_kbit=5000, ul_speed_kbit=2000)
        assert step.quality == 80
        assert step.dl_speed_kbit == 5000

    def test_step_rejects_quality_and_advanced(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            QosProfileStep(
                duration_sec=10,
                quality=80,
                advanced=QosQualityAdvanced(delay_ms=100),
            )

    def test_step_rejects_empty(self):
        with pytest.raises(ValueError, match="At least one"):
            QosProfileStep(duration_sec=10)

    def test_step_quality_range_min(self):
        step = QosProfileStep(duration_sec=10, quality=0)
        assert step.quality == 0

    def test_step_quality_range_max(self):
        step = QosProfileStep(duration_sec=10, quality=100)
        assert step.quality == 100

    def test_step_quality_over_max(self):
        with pytest.raises(Exception):
            QosProfileStep(duration_sec=10, quality=101)

    def test_step_quality_below_min(self):
        with pytest.raises(Exception):
            QosProfileStep(duration_sec=10, quality=-1)

    def test_step_duration_must_be_positive(self):
        with pytest.raises(Exception):
            QosProfileStep(duration_sec=0, quality=50)

    def test_profile_mode_values(self):
        assert set(QosProfileMode) == {
            QosProfileMode.loop,
            QosProfileMode.bounce,
            QosProfileMode.once,
            QosProfileMode.once_hold_last,
        }

    def test_profile_valid(self):
        p = QosProfile(
            id="test",
            description="Test profile",
            mode=QosProfileMode.loop,
            steps=[QosProfileStep(duration_sec=10, quality=80)],
        )
        assert p.id == "test"
        assert p.description == "Test profile"
        assert len(p.steps) == 1

    def test_profile_empty_steps_rejected(self):
        with pytest.raises(Exception):
            QosProfile(id="test", description="", mode=QosProfileMode.loop, steps=[])

    def test_start_request_profile_id_only(self):
        req = QosProfileStartRequest(profile_id="4g_urban_moving")
        assert req.profile_id == "4g_urban_moving"

    def test_start_request_inline_quality(self):
        req = QosProfileStartRequest(download_quality=80)
        assert req.download_quality == 80
        assert req.profile_id is None

    def test_start_request_inline_speed(self):
        req = QosProfileStartRequest(download_speed_kbit=8000, upload_speed_kbit=3000)
        assert req.download_speed_kbit == 8000

    def test_start_request_rejects_both(self):
        with pytest.raises(ValueError, match="Cannot specify both"):
            QosProfileStartRequest(profile_id="test", download_quality=80)

    def test_start_request_rejects_empty(self):
        with pytest.raises(ValueError, match="Must specify"):
            QosProfileStartRequest()

    def test_start_request_inline_advanced(self):
        req = QosProfileStartRequest(
            advanced=QosQualityAdvanced(delay_ms=100, jitter_ms=20)
        )
        assert req.advanced is not None

    def test_profile_state_inactive(self):
        st = QosProfileState(interface="wlan0", active=False)
        assert not st.active
        assert st.profile_id is None

    def test_profile_state_active(self):
        st = QosProfileState(
            interface="wlan0",
            active=True,
            profile_id="test",
            description="Test",
            source_file="default.json",
            mode=QosProfileMode.loop,
            steps=3,
            current_step=QosProfileStepState(index=0, elapsed_sec=5, duration_sec=10),
            total_elapsed_sec=5,
        )
        assert st.active
        assert st.description == "Test"
        assert st.steps == 3
        assert st.source_file == "default.json"

    def test_step_state(self):
        ss = QosProfileStepState(index=2, elapsed_sec=5, duration_sec=30)
        assert ss.index == 2


# ---------------------------------------------------------------------------
# Catalogue loading tests
# ---------------------------------------------------------------------------


class TestQosProfileCatalogue:
    """Tests for catalogue loading (multi-file, schema validation)."""

    @pytest.fixture
    def catalogue_dir(self, tmp_path):
        """Create a temp catalogue directory with schema from the real project."""
        import shutil

        schema_src = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "wilab", "data", "qos-profiles", "profile.schema.json",
        )
        shutil.copy(schema_src, tmp_path / "profile.schema.json")
        return tmp_path

    def _write_json(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f)

    def test_load_single_file(self, catalogue_dir):
        profiles = [
            {
                "id": "test1",
                "description": "Test profile 1",
                "mode": "loop",
                "steps": [{"duration_sec": 10, "quality": 80}],
            }
        ]
        self._write_json(catalogue_dir / "default.json", profiles)
        pm = QosProfileManager(str(catalogue_dir))
        assert len(pm.list_profiles()) == 1
        assert pm.get_profile("test1") is not None

    def test_default_loaded_first(self, catalogue_dir):
        """default.json profiles win over other files."""
        p1 = [{"id": "dup", "description": "Default", "mode": "loop", "steps": [{"duration_sec": 10, "quality": 80}]}]
        p2 = [{"id": "dup", "description": "Other", "mode": "once", "steps": [{"duration_sec": 5, "quality": 50}]}]
        self._write_json(catalogue_dir / "default.json", p1)
        self._write_json(catalogue_dir / "extra.json", p2)
        pm = QosProfileManager(str(catalogue_dir))
        assert pm.get_profile("dup").description == "Default"

    def test_duplicate_id_skipped_with_warning(self, catalogue_dir, caplog):
        import logging

        p1 = [{"id": "dup", "description": "First", "mode": "loop", "steps": [{"duration_sec": 10, "quality": 80}]}]
        p2 = [{"id": "dup", "description": "Second", "mode": "once", "steps": [{"duration_sec": 5, "quality": 50}]}]
        self._write_json(catalogue_dir / "default.json", p1)
        self._write_json(catalogue_dir / "zzz.json", p2)
        with caplog.at_level(logging.WARNING):
            pm = QosProfileManager(str(catalogue_dir))
        assert len(pm.list_profiles()) == 1
        assert "conflicts with an existing entry" in caplog.text

    def test_invalid_json_skipped(self, catalogue_dir, caplog):
        import logging

        (catalogue_dir / "default.json").write_text("NOT JSON{{{")
        with caplog.at_level(logging.WARNING):
            pm = QosProfileManager(str(catalogue_dir))
        assert len(pm.list_profiles()) == 0
        assert "invalid JSON" in caplog.text.lower() or "Skipping" in caplog.text

    def test_schema_validation_failure_skipped(self, catalogue_dir, caplog):
        import logging

        # Missing required 'steps' field
        bad = [{"id": "bad", "description": "no steps", "mode": "loop"}]
        self._write_json(catalogue_dir / "default.json", bad)
        with caplog.at_level(logging.WARNING):
            pm = QosProfileManager(str(catalogue_dir))
        assert len(pm.list_profiles()) == 0

    # --- T-19 (BUG-9): a wrong custom profile never stops the service

    def test_t19_profile_with_empty_advanced_is_skipped_valid_one_kept(self, catalogue_dir, caplog):
        """BUG-9: `"advanced": {}` stopped QosProfileManager (and the service) with a ValidationError."""
        import logging

        profiles = [
            {"id": "good", "description": "", "mode": "loop", "steps": [{"duration_sec": 5, "quality": 70}]},
            {"id": "x", "description": "", "mode": "loop", "steps": [{"duration_sec": 5, "advanced": {}}]},
        ]
        self._write_json(catalogue_dir / "custom.json", profiles)
        with caplog.at_level(logging.WARNING):
            pm = QosProfileManager(str(catalogue_dir))
        assert pm.get_profile("good") is not None
        assert pm.get_profile("x") is None
        assert "'x'" in caplog.text

    def test_t19_profile_the_model_refuses_is_skipped(self, catalogue_dir, monkeypatch):
        """Schema and model may still disagree: the model's refusal skips the profile too."""
        profiles = [
            {"id": "good", "description": "", "mode": "loop", "steps": [{"duration_sec": 5, "quality": 70}]},
            {"id": "odd", "description": "", "mode": "loop", "steps": [{"duration_sec": 5, "quality": 70}]},
        ]
        self._write_json(catalogue_dir / "default.json", profiles)
        real_step = qos_profile_module.QosProfileStep

        def step(**fields):
            if fields["quality"] == 70 and step.calls == 1:
                raise ValueError("refused by the model")
            step.calls += 1
            return real_step(**fields)

        step.calls = 0
        monkeypatch.setattr(qos_profile_module, "QosProfileStep", step)
        pm = QosProfileManager(str(catalogue_dir))
        assert [p.id for p in pm.list_profiles()] == ["good"]

    def test_t19_unreadable_schema_starts_with_an_empty_catalogue(self, catalogue_dir):
        (catalogue_dir / "profile.schema.json").write_text("{not json")
        self._write_json(catalogue_dir / "default.json", [
            {"id": "a", "description": "", "mode": "loop", "steps": [{"duration_sec": 5, "quality": 70}]},
        ])
        pm = QosProfileManager(str(catalogue_dir))
        assert pm.list_profiles() == []

    def test_multiple_files_merge(self, catalogue_dir):
        p1 = [{"id": "a", "description": "A", "mode": "loop", "steps": [{"duration_sec": 10, "quality": 80}]}]
        p2 = [{"id": "b", "description": "B", "mode": "once", "steps": [{"duration_sec": 5, "quality": 50}]}]
        self._write_json(catalogue_dir / "default.json", p1)
        self._write_json(catalogue_dir / "custom.json", p2)
        pm = QosProfileManager(str(catalogue_dir))
        assert len(pm.list_profiles()) == 2
        assert pm.get_profile("a") is not None
        assert pm.get_profile("b") is not None

    def test_load_real_default_catalogue(self):
        """Load the real default.json shipped with the project."""
        catalogue_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "wilab", "data", "qos-profiles",
        )
        pm = QosProfileManager(catalogue_dir)
        profiles = pm.list_profiles()
        assert len(profiles) == 10
        ids = {p.id for p in profiles}
        assert "4g_urban_stationary" in ids
        assert "satellite_link" in ids
        assert "progressive_degradation" in ids


# ---------------------------------------------------------------------------
# QosProfileManager execution tests
# ---------------------------------------------------------------------------


class _FastEvent(threading.Event):
    """A step lasts whole seconds (the model accepts nothing shorter): wait a twentieth."""

    def wait(self, timeout=None):
        return super().wait(None if timeout is None else timeout / 20)


def _wait_until(predicate, timeout: float = 5.0):
    """Poll instead of sleeping for a fixed time: no thin margins on a loaded machine."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("condition not reached")


class TestQosProfileManager:
    """Tests for profile execution logic."""

    @pytest.fixture
    def qos(self, monkeypatch):
        """Create a QosManager with mocked tc/ip commands."""
        from wilab.network import qos as qos_mod

        self.apply_calls = []

        original_apply = QosManager.apply_qos

        def mock_tc(args, **kwargs):
            return ""

        def mock_command(cmd, **kwargs):
            return ""

        monkeypatch.setattr(qos_mod, "execute_tc", mock_tc)
        monkeypatch.setattr(qos_mod, "execute_command", mock_command)

        mgr = QosManager()

        # Wrap apply_qos to record calls
        def tracking_apply(interface, **kwargs):
            self.apply_calls.append(kwargs)
            return original_apply(mgr, interface, **kwargs)

        monkeypatch.setattr(mgr, "apply_qos", tracking_apply)

        return mgr

    @pytest.fixture
    def pm(self, monkeypatch):
        """Create a QosProfileManager with the real catalogue; its steps run 20 times faster."""
        catalogue_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "wilab", "data", "qos-profiles",
        )
        active_profile = qos_profile_module._ActiveProfile
        monkeypatch.setattr(
            qos_profile_module, "_ActiveProfile",
            lambda **fields: active_profile(stop_event=_FastEvent(), **fields),
        )
        return QosProfileManager(catalogue_dir)

    def test_list_profiles(self, pm):
        profiles = pm.list_profiles()
        assert len(profiles) >= 10

    def test_get_profile_existing(self, pm):
        p = pm.get_profile("4g_urban_stationary")
        assert p is not None
        assert p.id == "4g_urban_stationary"
        assert p.description != ""
        assert p.source_file == "default.json"

    def test_get_profile_nonexistent(self, pm):
        assert pm.get_profile("nonexistent") is None

    def test_is_active_lifecycle(self, pm, qos):
        assert not pm.is_active("wlan0")

        profile = QosProfile(
            id="test",
            description="test",
            mode=QosProfileMode.once_hold_last,
            steps=[QosProfileStep(duration_sec=1, quality=80)],
        )
        pm.start_profile("wlan0", profile, qos)
        assert pm.is_active("wlan0")

        pm.stop_profile("wlan0", qos)
        assert not pm.is_active("wlan0")

    def test_start_raises_if_already_active(self, pm, qos):
        profile = QosProfile(
            id="test",
            description="test",
            mode=QosProfileMode.once_hold_last,
            steps=[QosProfileStep(duration_sec=1, quality=80)],
        )
        pm.start_profile("wlan0", profile, qos)
        with pytest.raises(RuntimeError, match="already active"):
            pm.start_profile("wlan0", profile, qos)
        pm.stop_profile("wlan0", qos)

    def test_stop_clears_qos(self, pm, qos):
        profile = QosProfile(
            id="test",
            description="test",
            mode=QosProfileMode.once_hold_last,
            steps=[QosProfileStep(duration_sec=1, quality=80)],
        )
        pm.start_profile("wlan0", profile, qos)
        _wait_until(lambda: self.apply_calls)  # the thread applied the step
        pm.stop_profile("wlan0", qos)

        state = qos.get_status("wlan0")
        assert state is not None
        assert not state.active

    def test_stop_keeps_profile_tracked_if_worker_does_not_exit(self, pm, qos):
        from unittest.mock import Mock

        profile = Mock()
        profile.thread.is_alive.return_value = True
        pm._active["wlan0"] = profile
        with pytest.raises(RuntimeError, match="did not stop"):
            pm.stop_profile("wlan0", qos)
        assert pm._active["wlan0"] is profile

    def test_step_applies_all_six_fields(self, pm, qos):
        profile = QosProfile(
            id="test",
            description="test",
            mode=QosProfileMode.once_hold_last,
            steps=[QosProfileStep(duration_sec=1, quality=80, dl_speed_kbit=5000)],
        )
        pm.start_profile("wlan0", profile, qos)
        _wait_until(lambda: self.apply_calls)
        pm.stop_profile("wlan0", qos)

        assert len(self.apply_calls) >= 1
        call = self.apply_calls[0]
        # All 6 fields should be passed explicitly
        assert "download_speed_kbit" in call
        assert "upload_speed_kbit" in call
        assert "download_quality" in call
        assert "upload_quality" in call
        assert "download_quality_advanced" in call
        assert "upload_quality_advanced" in call
        # quality maps symmetrically
        assert call["download_quality"] == 80
        assert call["upload_quality"] == 80
        assert call["download_speed_kbit"] == 5000
        # unset fields should be None (step isolation)
        assert call["upload_speed_kbit"] is None

    def test_once_mode_finishes(self, pm, qos):
        profile = QosProfile(
            id="test",
            description="test",
            mode=QosProfileMode.once,
            steps=[QosProfileStep(duration_sec=1, quality=80)],
        )
        pm.start_profile("wlan0", profile, qos)
        _wait_until(lambda: not pm.is_active("wlan0"))  # ends by itself after its only step
        assert len(self.apply_calls) == 1

    def test_loop_mode_wraps(self, pm, qos):
        """Loop mode should wrap step_index back to 0."""
        profile = QosProfile(
            id="test",
            description="test",
            mode=QosProfileMode.loop,
            steps=[
                QosProfileStep(duration_sec=1, quality=80),
                QosProfileStep(duration_sec=1, quality=50),
            ],
        )
        pm.start_profile("wlan0", profile, qos)
        # After two full steps it is on step 0 again: step0, step1, step0
        _wait_until(lambda: len(self.apply_calls) >= 3)
        state = pm.get_state("wlan0")
        assert state is not None
        assert state.active
        pm.stop_profile("wlan0", qos)
        assert [c["download_quality"] for c in self.apply_calls][:3] == [80, 50, 80]

    def test_bounce_mode_reverses(self, pm, qos):
        """Bounce mode: 0→1→2→1→0→1→... without duplicating boundary steps."""
        profile = QosProfile(
            id="test",
            description="test",
            mode=QosProfileMode.bounce,
            steps=[
                QosProfileStep(duration_sec=1, quality=90),
                QosProfileStep(duration_sec=1, quality=50),
                QosProfileStep(duration_sec=1, quality=10),
            ],
        )
        pm.start_profile("wlan0", profile, qos)
        # Steps 0 → 1 → 2 → 1 → 0
        _wait_until(lambda: len(self.apply_calls) >= 5)
        pm.stop_profile("wlan0", qos)

        # Verify the quality sequence: 90, 50, 10, 50, 90, ...
        qualities = [c["download_quality"] for c in self.apply_calls]
        assert qualities[:5] == [90, 50, 10, 50, 90]

    def test_hold_mode_holds_last_step(self, pm, qos):
        profile = QosProfile(
            id="test",
            description="test",
            mode=QosProfileMode.once_hold_last,
            steps=[
                QosProfileStep(duration_sec=1, quality=90),
                QosProfileStep(duration_sec=1, quality=50),
            ],
        )
        pm.start_profile("wlan0", profile, qos)
        # Both steps run, then it holds on the last one
        _wait_until(lambda: pm.get_state("wlan0").step_index == 1)
        time.sleep(0.2)  # four step durations: it must not move on or end
        assert pm.is_active("wlan0")
        state = pm.get_state("wlan0")
        assert state.step_index == 1  # holding on last step
        assert len(self.apply_calls) == 2
        pm.stop_profile("wlan0", qos)

    def test_build_inline_profile(self):
        profile = QosProfileManager.build_inline_profile(
            download_speed_kbit=8000,
            download_quality=80,
        )
        assert profile.mode == QosProfileMode.once_hold_last
        assert len(profile.steps) == 1
        assert profile.steps[0].dl_speed_kbit == 8000
        assert profile.steps[0].quality == 80
        assert ":generated_static" in profile.id
        assert profile.source_file == "generated"

    def test_build_inline_profile_advanced(self):
        adv = QosQualityAdvanced(delay_ms=100, jitter_ms=20)
        profile = QosProfileManager.build_inline_profile(advanced=adv)
        assert profile.steps[0].advanced is not None
        assert profile.steps[0].quality is None

    def test_get_state_returns_none_for_unknown(self, pm):
        assert pm.get_state("unknown_iface") is None


# ---------------------------------------------------------------------------
# API endpoint tests (via TestClient)
# ---------------------------------------------------------------------------


class TestQosProfileAPI:
    """Tests for QoS Profile API endpoints."""

    @pytest.fixture
    def client(self, monkeypatch, app):
        from fastapi.testclient import TestClient

        from wilab.network import qos as qos_mod

        self.tc_calls = []

        def mock_tc(args, **kwargs):
            self.tc_calls.append(args)
            return ""

        def mock_command(cmd, **kwargs):
            return ""

        monkeypatch.setattr(qos_mod, "execute_tc", mock_tc)
        monkeypatch.setattr(qos_mod, "execute_command", mock_command)

        return TestClient(app)

    @pytest.fixture
    def auth_headers(self, config):
        return {"Authorization": f"Bearer {config.auth_token}"}

    @pytest.fixture
    def reservation_id(self, client, auth_headers, monkeypatch, context):
        """Create a reservation and start a network, return reservation_id."""
        from wilab.config import load_config
        from wilab.reservation import ReservationManager

        cfg = load_config()
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(context, 'reservations', rmgr)

        # Reserve a device
        resp = client.post(
            "/api/v2/reservations",
            headers=auth_headers,
            json={"duration_seconds": 300},
        )
        assert resp.status_code == 200, resp.text
        rid = resp.json()["reservation_id"]

        # Mock DHCP so start_network works without root
        mgr = context.manager

        monkeypatch.setattr(mgr.dhcp_server, 'start', lambda *a, **kw: {
            'gateway': '192.168.120.1',
            'dhcp_range': '192.168.120.10,192.168.120.250',
            'config_file': '/tmp/mock.conf',
        })
        monkeypatch.setattr(mgr.dhcp_server, 'stop', lambda *a, **kw: None)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.hostapd_manager, 'stop', lambda *a, **kw: None)

        # Start a network
        resp = create_network(client, auth_headers, f"/api/v2/reservations/{rid}/network", network_body(ssid="QoSProfileTest", channel=6, encryption="open", band="2.4ghz", tx_power_level=4))[1]
        assert resp.status_code == 200, resp.text
        return rid

    # --- Catalogue endpoints ---

    def test_list_profiles(self, client):
        resp = client.get("/api/v2/qos/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 10
        assert all("id" in p for p in data)
        assert all("description" in p for p in data)
        assert all("source_file" in p for p in data)
        assert all(p["source_file"] == "default.json" for p in data)

    # --- Profile application endpoints ---

    def test_start_profile_from_catalogue(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
            json={"profile_id": "4g_urban_stationary"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["profile_id"] == "4g_urban_stationary"
        assert data["description"] != ""
        assert data["source_file"] == "default.json"
        assert data["mode"] == "loop"
        assert data["steps"] == 4
        assert data["current_step"] is not None
        assert data["total_elapsed_sec"] is not None

        # Clean up
        client.delete(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
        )

    def test_start_inline_qos(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
            json={"download_speed_kbit": 1000, "download_quality": 40},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert ":generated_static" in data["profile_id"]
        assert data["source_file"] == "generated"
        assert data["mode"] == "once-hold-last"
        assert data["steps"] == 1

        client.delete(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
        )

    @pytest.mark.parametrize("body", [
        {"download_quality": 40, "upload_quality": 90},
        {"download_quality": 40, "advanced": {"delay_ms": 100}},
        {"upload_quality": 40, "advanced": {"delay_ms": 100}},
    ])
    def test_t19_inline_qos_that_cannot_be_applied_is_refused(self, client, auth_headers, reservation_id, body):
        """NET-11: 40 down and 90 up applied 40 both ways and answered 200; quality with advanced was dropped."""
        resp = client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile", headers=auth_headers, json=body,
        )
        assert resp.status_code == 422, resp.text

    def test_t19_equal_qualities_are_accepted(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers, json={"download_quality": 60, "upload_quality": 60},
        )
        assert resp.status_code == 200, resp.text
        client.delete(f"/api/v2/reservations/{reservation_id}/qos/profile", headers=auth_headers)

    def test_start_profile_unknown_id(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
            json={"profile_id": "nonexistent_profile"},
        )
        assert resp.status_code == 422  # a body error; 404 only means the reservation is gone
        assert resp.json()['detail']['message'].startswith('profile_id: ')

    def test_start_profile_already_active_409(self, client, auth_headers, reservation_id):
        client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
            json={"profile_id": "4g_urban_stationary"},
        )
        resp = client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
            json={"profile_id": "4g_urban_moving"},
        )
        assert resp.status_code == 409

        client.delete(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
        )

    def test_start_both_profile_and_params_422(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
            json={"profile_id": "4g_urban_stationary", "download_quality": 80},
        )
        assert resp.status_code == 422

    def test_start_empty_body_422(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 422

    def test_get_profile_state_active(self, client, auth_headers, reservation_id):
        client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
            json={"profile_id": "4g_urban_stationary"},
        )
        resp = client.get(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["profile_id"] == "4g_urban_stationary"
        assert data["source_file"] == "default.json"

        client.delete(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
        )

    def test_get_profile_state_inactive(self, client, auth_headers, reservation_id):
        resp = client.get(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False
        assert data["profile_id"] is None
        assert data["source_file"] is None
        assert data["steps"] is None

    def test_delete_profile(self, client, auth_headers, reservation_id):
        client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
            json={"profile_id": "4g_urban_stationary"},
        )
        resp = client.delete(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "4g_urban_stationary" in resp.json()["detail"]
        assert "deactivated correctly" in resp.json()["detail"]

        # Verify cleared
        resp = client.get(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
        )
        assert resp.json()["active"] is False

    def test_delete_when_no_profile_active(self, client, auth_headers, reservation_id):
        resp = client.delete(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()['detail']['code'] in (1007, 1011)  # no network, or no profile

    def test_start_requires_auth(self, client, reservation_id):
        resp = client.post(
            f"/api/v2/reservations/{reservation_id}/qos/profile",
            json={"profile_id": "4g_urban_stationary"},
        )
        assert resp.status_code in (401, 403)

    def test_start_invalid_reservation(self, client, auth_headers):
        resp = client.post(
            "/api/v2/reservations/nonexistent/qos/profile",
            headers=auth_headers,
            json={"profile_id": "4g_urban_stationary"},
        )
        assert resp.status_code == 404
