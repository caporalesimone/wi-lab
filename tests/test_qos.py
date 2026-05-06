"""Tests for QoS (Quality of Service) management."""

import pytest

from wilab.models import QosRequest, QosStatus, QosQualityAdvanced, NetemParams, DelayDistribution
from wilab.network.qos import QosManager, _SENTINEL


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------

class TestQosRequestModel:
    """Tests for QosRequest Pydantic model."""

    def test_valid_both_speeds(self):
        req = QosRequest(download_speed_kbit=8000, upload_speed_kbit=3000)
        assert req.download_speed_kbit == 8000
        assert req.upload_speed_kbit == 3000

    def test_valid_download_only(self):
        req = QosRequest(download_speed_kbit=5000)
        assert req.download_speed_kbit == 5000
        assert req.upload_speed_kbit is None

    def test_valid_upload_only(self):
        req = QosRequest(upload_speed_kbit=2000)
        assert req.upload_speed_kbit == 2000
        assert req.download_speed_kbit is None

    def test_null_resets(self):
        req = QosRequest(download_speed_kbit=None, upload_speed_kbit=None)
        assert req.download_speed_kbit is None
        assert req.upload_speed_kbit is None

    def test_min_speed(self):
        req = QosRequest(download_speed_kbit=1)
        assert req.download_speed_kbit == 1

    def test_max_speed(self):
        req = QosRequest(download_speed_kbit=1_000_000)
        assert req.download_speed_kbit == 1_000_000

    def test_speed_below_min(self):
        with pytest.raises(Exception):
            QosRequest(download_speed_kbit=0)

    def test_speed_above_max(self):
        with pytest.raises(Exception):
            QosRequest(download_speed_kbit=1_000_001)

    def test_negative_speed(self):
        with pytest.raises(Exception):
            QosRequest(download_speed_kbit=-1)


class TestQosStatusModel:
    """Tests for QosStatus response model."""

    def test_inactive(self):
        st = QosStatus(interface="wlan0", active=False)
        assert st.interface == "wlan0"
        assert not st.active
        assert st.download_speed_kbit is None

    def test_active_with_speed(self):
        st = QosStatus(interface="wlan0", active=True, download_speed_kbit=8000)
        assert st.active
        assert st.download_speed_kbit == 8000


# ---------------------------------------------------------------------------
# QosManager unit tests (mocked tc commands)
# ---------------------------------------------------------------------------

class TestQosManagerThrottle:
    """Tests for QosManager bandwidth throttling logic."""

    @pytest.fixture
    def qos(self, monkeypatch):
        """Create a QosManager with mocked tc/ip commands."""
        from wilab.network import qos as qos_mod

        self.tc_calls = []
        self.cmd_calls = []

        def mock_tc(args):
            self.tc_calls.append(args)
            return ""

        def mock_command(cmd, **kwargs):
            self.cmd_calls.append(cmd)
            return ""

        monkeypatch.setattr(qos_mod, "execute_tc", mock_tc)
        monkeypatch.setattr(qos_mod, "execute_command", mock_command)

        return QosManager()

    def test_apply_download_only(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 5000
        assert state.upload_speed_kbit is None
        assert state.active

        # Verify tc was called for HTB setup
        tc_ops = [c[0] for c in self.tc_calls]
        assert "qdisc" in tc_ops
        assert "class" in tc_ops

    def test_apply_upload_only(self, qos):
        qos.apply_qos("wlan0", upload_speed_kbit=2000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.upload_speed_kbit == 2000
        assert state.download_speed_kbit is None

        # IFB device should be allocated
        assert state.ifb_device is not None

    def test_apply_both_directions(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=8000, upload_speed_kbit=3000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 8000
        assert state.upload_speed_kbit == 3000
        assert state.active

    def test_update_download_speed(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000)
        qos.apply_qos("wlan0", download_speed_kbit=10000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 10000

    def test_omitted_field_keeps_current(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000, upload_speed_kbit=2000)
        # Only update download, upload should stay
        qos.apply_qos("wlan0", download_speed_kbit=8000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 8000
        assert state.upload_speed_kbit == 2000

    def test_null_resets_to_unlimited(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000, upload_speed_kbit=2000)
        qos.apply_qos("wlan0", download_speed_kbit=None)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit is None
        assert state.upload_speed_kbit == 2000

    def test_clear_all(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000, upload_speed_kbit=2000)
        qos.clear_qos("wlan0")

        state = qos.get_status("wlan0")
        assert state is not None
        assert not state.active
        assert state.download_speed_kbit is None
        assert state.upload_speed_kbit is None

    def test_clear_nonexistent_is_noop(self, qos):
        # Should not raise
        qos.clear_qos("wlan99")

    def test_get_status_unknown_interface(self, qos):
        assert qos.get_status("wlan99") is None

    def test_idempotent_apply(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000)
        tc_count_1 = len(self.tc_calls)
        qos.apply_qos("wlan0", download_speed_kbit=5000)
        # Second apply should still issue class change (idempotent)
        assert len(self.tc_calls) > tc_count_1

    def test_reset_both_removes_all(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000, upload_speed_kbit=2000)
        qos.apply_qos("wlan0", download_speed_kbit=None, upload_speed_kbit=None)

        state = qos.get_status("wlan0")
        assert state is not None
        assert not state.active

    def test_ifb_counter_increments(self, qos):
        qos.apply_qos("wlan0", upload_speed_kbit=2000)
        qos.clear_qos("wlan0")
        qos.apply_qos("wlan1", upload_speed_kbit=3000)

        st0 = qos.get_status("wlan1")
        assert st0 is not None
        assert st0.ifb_device == "ifb1"


class TestQosManagerSentinel:
    """Tests for _SENTINEL partial-update logic."""

    def test_resolve_sentinel_keeps_current(self):
        assert QosManager._resolve(_SENTINEL, 5000) == 5000

    def test_resolve_none_resets(self):
        assert QosManager._resolve(None, 5000) is None

    def test_resolve_value_updates(self):
        assert QosManager._resolve(8000, 5000) == 8000

    def test_resolve_sentinel_with_none_current(self):
        assert QosManager._resolve(_SENTINEL, None) is None


# ---------------------------------------------------------------------------
# Quality model tests
# ---------------------------------------------------------------------------

class TestQosQualityModels:
    """Tests for quality-related Pydantic models."""

    def test_quality_advanced_valid(self):
        adv = QosQualityAdvanced(
            packet_loss_percent=5.5,
            delay_ms=100,
            jitter_ms=20,
            corruption_percent=0.1,
            delay_distribution=DelayDistribution.normal,
        )
        assert adv.packet_loss_percent == 5.5
        assert adv.delay_ms == 100

    def test_quality_advanced_defaults(self):
        adv = QosQualityAdvanced()
        assert adv.packet_loss_percent is None
        assert adv.delay_distribution == DelayDistribution.normal

    def test_quality_advanced_pareto(self):
        adv = QosQualityAdvanced(delay_distribution=DelayDistribution.pareto)
        assert adv.delay_distribution == DelayDistribution.pareto

    def test_quality_advanced_corruption_max(self):
        adv = QosQualityAdvanced(corruption_percent=5.0)
        assert adv.corruption_percent == 5.0

    def test_quality_advanced_corruption_over_max(self):
        with pytest.raises(Exception):
            QosQualityAdvanced(corruption_percent=5.1)

    def test_quality_range_valid(self):
        req = QosRequest(download_quality=0)
        assert req.download_quality == 0
        req = QosRequest(download_quality=100)
        assert req.download_quality == 100

    def test_quality_range_invalid_above(self):
        with pytest.raises(Exception):
            QosRequest(download_quality=101)

    def test_quality_range_invalid_below(self):
        with pytest.raises(Exception):
            QosRequest(download_quality=-1)

    def test_netem_params_model(self):
        p = NetemParams(packet_loss_percent=2.5, delay_ms=50, jitter_ms=10)
        assert p.packet_loss_percent == 2.5
        assert p.corruption_percent == 0  # default

    def test_request_with_quality_and_speed(self):
        req = QosRequest(
            download_speed_kbit=8000,
            download_quality=80,
            upload_quality=65,
        )
        assert req.download_speed_kbit == 8000
        assert req.download_quality == 80
        assert req.upload_quality == 65

    def test_request_with_advanced_override(self):
        req = QosRequest(
            download_quality_advanced=QosQualityAdvanced(
                packet_loss_percent=10.0,
                delay_ms=200,
            ),
        )
        assert req.download_quality_advanced is not None
        assert req.download_quality_advanced.packet_loss_percent == 10.0


# ---------------------------------------------------------------------------
# QosManager quality tests
# ---------------------------------------------------------------------------

class TestQosManagerQuality:
    """Tests for quality formula and netem management."""

    @pytest.fixture
    def qos(self, monkeypatch):
        from wilab.network import qos as qos_mod

        self.tc_calls = []

        def mock_tc(args):
            self.tc_calls.append(args)
            return ""

        def mock_command(cmd, **kwargs):
            return ""

        monkeypatch.setattr(qos_mod, "execute_tc", mock_tc)
        monkeypatch.setattr(qos_mod, "execute_command", mock_command)

        return QosManager()

    def test_quality_formula_perfect(self):
        params = QosManager.quality_to_netem_params(100)
        assert params.packet_loss_percent == 0
        assert params.delay_ms == 0
        assert params.jitter_ms == 0
        assert params.corruption_percent == 0

    def test_quality_formula_zero(self):
        params = QosManager.quality_to_netem_params(0)
        assert params.packet_loss_percent == 30.0
        assert params.delay_ms == 1000
        assert params.jitter_ms == 300
        assert params.corruption_percent == 1.0

    def test_quality_formula_50(self):
        params = QosManager.quality_to_netem_params(50)
        assert params.packet_loss_percent == 7.5
        assert params.delay_ms == 250
        assert params.jitter_ms == 75

    def test_quality_formula_90(self):
        params = QosManager.quality_to_netem_params(90)
        assert params.packet_loss_percent == 0.3
        assert params.delay_ms == 10
        assert params.jitter_ms == 3

    def test_apply_download_quality(self, qos):
        qos.apply_qos("wlan0", download_quality=80)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_quality == 80
        assert state.active
        assert state.download_netem_params is not None
        assert state.download_netem_params.packet_loss_percent > 0

        # Check netem tc command was issued
        netem_calls = [c for c in self.tc_calls if "netem" in c]
        assert len(netem_calls) > 0

    def test_apply_upload_quality(self, qos):
        qos.apply_qos("wlan0", upload_quality=65)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.upload_quality == 65
        assert state.ifb_device is not None
        assert state.upload_netem_params is not None

    def test_apply_quality_and_speed(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=8000, download_quality=80)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 8000
        assert state.download_quality == 80
        assert state.download_netem_params is not None

    def test_quality_only_creates_htb(self, qos):
        """Quality without speed should still create HTB tree for netem chaining."""
        qos.apply_qos("wlan0", download_quality=50)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.htb_installed

    def test_advanced_override(self, qos):
        adv = QosQualityAdvanced(
            packet_loss_percent=5.5,
            delay_ms=140,
            jitter_ms=25,
            corruption_percent=0.2,
            delay_distribution=DelayDistribution.paretonormal,
        )
        qos.apply_qos("wlan0", download_quality_advanced=adv)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_netem_params is not None
        assert state.download_netem_params.packet_loss_percent == 5.5
        assert state.download_netem_params.delay_ms == 140
        assert state.download_netem_params.delay_distribution == "paretonormal"

    def test_reset_quality_to_none(self, qos):
        qos.apply_qos("wlan0", download_quality=80)
        qos.apply_qos("wlan0", download_quality=None)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_quality is None
        assert state.download_netem_params is None
        assert not state.active

    def test_quality_preserved_when_speed_updated(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=8000, download_quality=80)
        qos.apply_qos("wlan0", download_speed_kbit=12000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 12000
        assert state.download_quality == 80

    def test_speed_preserved_when_quality_updated(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=8000, download_quality=80)
        qos.apply_qos("wlan0", download_quality=50)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 8000
        assert state.download_quality == 50

    def test_clear_removes_quality(self, qos):
        qos.apply_qos("wlan0", download_quality=80, upload_quality=65)
        qos.clear_qos("wlan0")

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_quality is None
        assert state.upload_quality is None
        assert state.download_netem_params is None

    def test_netem_args_built_correctly(self):
        params = NetemParams(
            packet_loss_percent=5.0,
            delay_ms=100,
            jitter_ms=20,
            corruption_percent=0.1,
            delay_distribution="normal",
        )
        args = QosManager._build_netem_args(params)
        assert "loss" in args
        assert "5.0%" in args
        assert "delay" in args
        assert "100ms" in args
        assert "20ms" in args
        assert "corrupt" in args
        assert "0.1%" in args

    def test_netem_args_no_jitter_skips_distribution(self):
        params = NetemParams(delay_ms=100, jitter_ms=0)
        args = QosManager._build_netem_args(params)
        assert "delay" in args
        assert "distribution" not in args

    def test_netem_args_empty_when_all_zero(self):
        params = NetemParams()
        args = QosManager._build_netem_args(params)
        assert args == []
