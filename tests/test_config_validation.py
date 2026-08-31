"""Tests for the configuration validator (wilab/config_validation.py).

The validator is a pure function of a file, so these tests build inputs by mutating a
known-good baseline (the ``write_config`` fixture) and assert on the resulting report.

Covers TODOs/device-capabilities.md §12.2.
"""

import pytest
import yaml

from wilab.config import CAPABILITY_REGISTRY, CapabilityDef, CapabilityKind
from wilab.config_validation import (
    EXAMPLE_AUTH_TOKEN,
    Severity,
    ValidationIssue,
    ValidationReport,
    validate_config_file,
)


def paths(report, severity=None):
    """Issue paths in report order, optionally filtered by severity."""
    return [i.path for i in report.issues if severity is None or i.severity is severity]


def error_paths(report):
    return paths(report, Severity.ERROR)


# ==================================================================================================
# Phase 1 — structural
# ==================================================================================================


class TestStructural:
    def test_missing_file(self, tmp_path):
        report = validate_config_file(str(tmp_path / "nope.yaml"))
        assert report.unreadable is True
        assert report.ok is False
        assert len(report.issues) == 1
        assert "not found" in report.issues[0].message.lower()

    def test_malformed_yaml_does_not_cascade(self, write_config):
        path = write_config(raw_text="auth_token: [unclosed\n  bad: : :\n")
        report = validate_config_file(path)
        assert report.unreadable is True
        # A parse error must not produce a wall of "missing key" noise.
        assert len(report.issues) == 1
        assert "Invalid YAML" in report.issues[0].message

    def test_top_level_not_a_mapping(self, write_config):
        path = write_config(raw_text="- one\n- two\n")
        report = validate_config_file(path)
        assert report.unreadable is True
        assert "mapping" in report.issues[0].message

    def test_empty_file_is_readable_but_incomplete(self, write_config):
        """An empty file parses fine; it is simply missing every key."""
        path = write_config(raw_text="")
        report = validate_config_file(path)
        assert report.unreadable is False
        assert "auth_token" in error_paths(report)
        assert "networks" in error_paths(report)

    def test_bom_and_crlf_are_tolerated(self, tmp_path, valid_config):
        path = tmp_path / "bom.yaml"
        text = yaml.safe_dump(valid_config, sort_keys=False).replace("\n", "\r\n")
        path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        report = validate_config_file(str(path))
        assert report.ok, report.render()


# ==================================================================================================
# Phase 2/3 — presence and unknown keys
# ==================================================================================================


class TestPresence:
    def test_valid_config_passes(self, write_config):
        report = validate_config_file(write_config())
        assert report.ok, report.render()
        assert report.issues == ()

    @pytest.mark.parametrize("key", [
        "auth_token", "api_port", "max_timeout", "min_timeout",
        "allow_unlimited_reservation", "dhcp_base_network", "upstream_interface",
        "country_code", "dns_server", "internet_enabled_by_default",
        "networks", "cors_origins",
    ])
    def test_every_top_level_key_is_mandatory(self, write_config, key):
        """Including the ones that carry a Python default: no implicit defaults in the file."""
        report = validate_config_file(write_config(remove=[key]))
        assert key in error_paths(report)

    def test_missing_key_is_reported_exactly_once(self, write_config):
        """Regression guard for review finding SW-3.

        The presence phase and Pydantic both flag a missing key; without de-duplication
        the administrator sees every missing key twice.
        """
        report = validate_config_file(write_config(remove=["dhcp_base_network"]))
        assert error_paths(report).count("dhcp_base_network") == 1

    def test_missing_capabilities_block(self, write_config, valid_config):
        nets = [{"interface": "wls16", "display_name": "a"}]
        report = validate_config_file(write_config({"networks": nets}))
        assert "networks[0].capabilities" in error_paths(report)
        hint = next(i.hint for i in report.issues if i.path == "networks[0].capabilities")
        assert "2.4ghz" in hint and "5ghz" in hint

    def test_missing_single_capability_key(self, write_config):
        nets = [{"interface": "wls16", "display_name": "a", "capabilities": {"2.4ghz": True}}]
        report = validate_config_file(write_config({"networks": nets}))
        assert "networks[0].capabilities.5ghz" in error_paths(report)

    def test_capability_key_normalisation(self, write_config):
        """'5GHz' and ' 2.4ghz ' are the same keys as their canonical forms."""
        nets = [{
            "interface": "wls16", "display_name": "a",
            "capabilities": {" 2.4ghz ": True, "5GHz": False},
        }]
        report = validate_config_file(write_config({"networks": nets}))
        assert report.ok, report.render()

    def test_duplicate_capability_ids_after_normalisation(self, write_config):
        nets = [{
            "interface": "wls16", "display_name": "a",
            "capabilities": {"2.4ghz": True, "5ghz": False, "5GHz": True},
        }]
        report = validate_config_file(write_config({"networks": nets}))
        assert any("declared twice" in i.message for i in report.issues)

    def test_cors_origins_empty_list_accepted(self, write_config):
        assert validate_config_file(write_config({"cors_origins": []})).ok

    def test_cors_origins_null_accepted(self, write_config):
        assert validate_config_file(write_config({"cors_origins": None})).ok


class TestUnknownKeys:
    def test_unknown_top_level_key(self, write_config):
        report = validate_config_file(write_config({"typo_key": 1}))
        assert "typo_key" in error_paths(report)

    def test_unknown_network_key(self, write_config, valid_config):
        nets = valid_config["networks"]
        nets[0]["colour"] = "blue"
        report = validate_config_file(write_config({"networks": nets}))
        assert "networks[0].colour" in error_paths(report)

    def test_unknown_capability_id_lists_valid_ones(self, write_config, valid_config):
        nets = valid_config["networks"]
        nets[0]["capabilities"]["5ghzz"] = True
        report = validate_config_file(write_config({"networks": nets}))
        issue = next(i for i in report.issues if i.path == "networks[0].capabilities.5ghzz")
        assert "5ghz" in (issue.hint or "")


# ==================================================================================================
# Aggregation — the validator's core promise
# ==================================================================================================


class TestAggregation:
    def test_reports_every_problem_in_one_pass(self, write_config, valid_config):
        """Five independent faults must produce five issues, not one."""
        nets = valid_config["networks"]
        nets[0]["capabilities"] = {"2.4ghz": False, "5ghz": False}   # 1: group rule
        path = write_config({
            "networks": nets,
            "country_code": "italy",                                  # 2
            "dns_server": "not-an-ip",                                # 3
            "api_port": 99999,                                        # 4
        }, remove=["upstream_interface"])                             # 5
        report = validate_config_file(path)
        assert set(error_paths(report)) == {
            "networks[0].capabilities", "country_code", "dns_server",
            "api_port", "upstream_interface",
        }

    def test_issue_order_is_schema_position(self, write_config, valid_config):
        """The report reads top-to-bottom like the file, and the order is stable."""
        nets = valid_config["networks"]
        nets[0]["capabilities"] = {"2.4ghz": False, "5ghz": False}
        path = write_config({"networks": nets, "dns_server": "bad", "api_port": 0})
        first = error_paths(validate_config_file(path))
        second = error_paths(validate_config_file(path))
        assert first == second, "ordering must be deterministic"
        assert first.index("api_port") < first.index("dns_server")
        assert first.index("dns_server") < first.index("networks[0].capabilities")

    def test_rules_are_defensive_about_missing_inputs(self, write_config):
        """A rule whose key is absent stays silent instead of piling on."""
        report = validate_config_file(write_config(remove=["min_timeout", "max_timeout"]))
        assert error_paths(report).count("min_timeout") == 1  # only "missing key"
        assert not any("greater than" in i.message for i in report.issues)

    def test_a_raising_rule_does_not_kill_the_report(self, write_config, monkeypatch):
        from wilab import config_validation

        def exploding_rule(ctx):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            config_validation, "_RULES",
            list(config_validation._RULES) + [("networks", False, exploding_rule)],
        )
        report = validate_config_file(write_config({"dns_server": "bad"}))
        assert any("Internal validation error" in i.message for i in report.issues)
        # The other rules still ran.
        assert "dns_server" in error_paths(report)


# ==================================================================================================
# Phase 5 — custom rules
# ==================================================================================================


class TestCapabilityGroupRule:
    def test_both_bands_false_is_an_error(self, write_config, valid_config):
        nets = valid_config["networks"]
        nets[0]["capabilities"] = {"2.4ghz": False, "5ghz": False}
        report = validate_config_file(write_config({"networks": nets}))
        issue = next(i for i in report.issues if i.path == "networks[0].capabilities")
        assert "group 'band'" in issue.message

    @pytest.mark.parametrize("caps", [
        {"2.4ghz": True, "5ghz": False},
        {"2.4ghz": False, "5ghz": True},
        {"2.4ghz": True, "5ghz": True},
    ])
    def test_one_enabled_band_is_enough(self, write_config, valid_config, caps):
        nets = valid_config["networks"]
        nets[0]["capabilities"] = caps
        assert validate_config_file(write_config({"networks": nets})).ok

    def test_yaml_string_is_not_an_enabled_band(self, write_config, valid_config):
        """"yes" is a string in YAML 1.2 and must not count as True."""
        nets = valid_config["networks"]
        nets[0]["capabilities"] = {"2.4ghz": "yes", "5ghz": False}
        report = validate_config_file(write_config({"networks": nets}))
        assert "networks[0].capabilities" in error_paths(report)          # group rule fired
        assert "networks[0].capabilities.2.4ghz" in error_paths(report)   # type error too

    def test_rule_is_generic_not_band_specific(self, write_config, valid_config, monkeypatch):
        """Capabilities with group=None may all be false without tripping the group rule.

        Proves the rule scans the registry's ``group`` metadata rather than hardcoding
        ``2.4ghz``/``5ghz``, which is what lets a future policy capability such as
        ``change-ssid: false`` sit on a perfectly usable device.
        """
        policy_registry = {
            cap: CapabilityDef(
                id=cap,
                label=definition.label,
                kind=CapabilityKind.POLICY,
                group=None,                      # <- no longer members of the 'band' group
            )
            for cap, definition in CAPABILITY_REGISTRY.items()
        }
        monkeypatch.setattr("wilab.config_validation.CAPABILITY_REGISTRY", policy_registry)

        nets = valid_config["networks"]
        nets[0]["capabilities"] = {"2.4ghz": False, "5ghz": False}
        report = validate_config_file(write_config({"networks": nets}))
        assert not any("group" in i.message for i in report.issues), (
            "with no capability in the 'band' group the rule must stay silent, "
            "even though every capability is false"
        )

    def test_group_rule_still_fires_with_the_real_registry(self, write_config, valid_config):
        """Companion to the test above: the same input *does* fail with the shipped registry."""
        nets = valid_config["networks"]
        nets[0]["capabilities"] = {"2.4ghz": False, "5ghz": False}
        report = validate_config_file(write_config({"networks": nets}))
        assert any("group 'band'" in i.message for i in report.issues)


class TestScalarRules:
    def test_min_timeout_below_floor(self, write_config):
        report = validate_config_file(write_config({"min_timeout": 5}))
        assert "min_timeout" in error_paths(report)

    def test_min_timeout_at_floor_is_accepted(self, write_config):
        assert validate_config_file(write_config({"min_timeout": 10})).ok

    def test_min_greater_than_max(self, write_config):
        """Gap that exists in the shipped code: such a config makes every reservation fail."""
        report = validate_config_file(write_config({"min_timeout": 600, "max_timeout": 300}))
        assert any("must not be greater than" in i.message for i in report.issues)

    def test_max_timeout_must_be_positive(self, write_config):
        report = validate_config_file(write_config({"max_timeout": 0}))
        assert "max_timeout" in error_paths(report)

    def test_empty_networks_list(self, write_config):
        """Gap that exists in the shipped code: an empty pool starts cleanly and is useless."""
        report = validate_config_file(write_config({"networks": []}))
        assert "networks" in error_paths(report)

    def test_empty_auth_token(self, write_config):
        """Gap that exists in the shipped code: the empty Bearer token would authenticate."""
        report = validate_config_file(write_config({"auth_token": ""}))
        assert "auth_token" in error_paths(report)

    def test_example_auth_token_is_a_warning_only(self, write_config):
        report = validate_config_file(write_config({"auth_token": EXAMPLE_AUTH_TOKEN}))
        assert report.ok is True
        assert "auth_token" in paths(report, Severity.WARNING)

    def test_bad_dhcp_base_network(self, write_config):
        report = validate_config_file(write_config({"dhcp_base_network": "not-a-network"}))
        assert "dhcp_base_network" in error_paths(report)

    def test_dhcp_base_network_must_be_24(self, write_config):
        report = validate_config_file(write_config({"dhcp_base_network": "192.168.0.0/16"}))
        assert any("/24" in i.message for i in report.issues)

    def test_third_octet_overflow(self, write_config, valid_config):
        nets = [
            {"interface": f"wls{i}", "display_name": f"a{i}",
             "capabilities": {"2.4ghz": True, "5ghz": False}}
            for i in range(6)
        ]
        report = validate_config_file(
            write_config({"dhcp_base_network": "192.168.252.0/24", "networks": nets})
        )
        assert any("overflow" in i.message for i in report.issues)

    def test_duplicate_interfaces(self, write_config):
        nets = [
            {"interface": "wls16", "display_name": "a",
             "capabilities": {"2.4ghz": True, "5ghz": False}},
            {"interface": "wls16", "display_name": "b",
             "capabilities": {"2.4ghz": True, "5ghz": False}},
        ]
        report = validate_config_file(write_config({"networks": nets}))
        assert "networks[1].interface" in error_paths(report)

    def test_duplicate_display_name_is_a_warning(self, write_config):
        nets = [
            {"interface": "wls16", "display_name": "same",
             "capabilities": {"2.4ghz": True, "5ghz": False}},
            {"interface": "wls17", "display_name": "same",
             "capabilities": {"2.4ghz": True, "5ghz": False}},
        ]
        report = validate_config_file(write_config({"networks": nets}))
        assert report.ok is True
        assert "networks[1].display_name" in paths(report, Severity.WARNING)

    def test_empty_display_name_is_an_error(self, write_config):
        nets = [{"interface": "wls16", "display_name": "  ",
                 "capabilities": {"2.4ghz": True, "5ghz": False}}]
        report = validate_config_file(write_config({"networks": nets}))
        assert "networks[0].display_name" in error_paths(report)

    def test_invalid_dns_server(self, write_config):
        report = validate_config_file(write_config({"dns_server": "8.8.8"}))
        assert "dns_server" in error_paths(report)

    @pytest.mark.parametrize("code", ["italy", "it", "ITA", ""])
    def test_invalid_country_code(self, write_config, code):
        report = validate_config_file(write_config({"country_code": code}))
        assert "country_code" in error_paths(report)

    @pytest.mark.parametrize("port", [0, 65536, -1])
    def test_api_port_out_of_range(self, write_config, port):
        report = validate_config_file(write_config({"api_port": port}))
        assert "api_port" in error_paths(report)

    def test_privileged_port_is_a_warning(self, write_config):
        report = validate_config_file(write_config({"api_port": 80}))
        assert report.ok is True
        assert "api_port" in paths(report, Severity.WARNING)

    def test_malformed_cors_origin(self, write_config):
        report = validate_config_file(write_config({"cors_origins": ["localhost:4200"]}))
        assert "cors_origins[0]" in error_paths(report)

    def test_non_empty_cors_is_a_warning(self, write_config):
        report = validate_config_file(write_config({"cors_origins": ["http://localhost:4200"]}))
        assert report.ok is True
        assert "cors_origins" in paths(report, Severity.WARNING)

    def test_empty_upstream_interface(self, write_config):
        report = validate_config_file(write_config({"upstream_interface": "  "}))
        assert "upstream_interface" in error_paths(report)


# ==================================================================================================
# Phase 6 — hardware (opt-in)
# ==================================================================================================


class TestHardwarePhase:
    def test_static_validation_never_touches_the_hardware(self, write_config, monkeypatch):
        """This is what makes --validate-config usable on a laptop."""
        called = []
        from wilab.wifi import interface as interface_mod

        monkeypatch.setattr(
            interface_mod, "validate_interface",
            lambda iface: called.append(iface),
        )
        validate_config_file(write_config(), check_hardware=False)
        assert called == []

    def test_conftest_monkeypatch_reaches_the_validator(self, write_config, monkeypatch):
        """Regression guard for review finding DEV-1.

        The validator must import validate_interface *inside* the rule. A module-level
        import would capture the original function and silently defeat the patch that the
        whole test suite relies on — every config load would then shell out to `iw`.
        """
        called = []
        from wilab.wifi import interface as interface_mod

        monkeypatch.setattr(
            interface_mod, "validate_interface",
            lambda iface: called.append(iface),
        )
        validate_config_file(write_config(), check_hardware=True)
        assert called == ["wls16"], "the rule must resolve the helper at call time"

    def test_unusable_interface_is_reported(self, write_config, monkeypatch):
        from wilab.wifi import interface as interface_mod

        def boom(iface):
            raise interface_mod.InterfaceError(f"Interface {iface} does not exist")

        monkeypatch.setattr(interface_mod, "validate_interface", boom)
        report = validate_config_file(write_config(), check_hardware=True)
        assert "networks[0].interface" in error_paths(report)

    def test_subnet_colliding_with_a_host_route_is_reported(self, write_config, monkeypatch):
        from wilab.network import commands as commands_mod

        monkeypatch.setattr(
            commands_mod, "execute_command",
            lambda cmd, **kw: "192.168.120.0/24 dev eth0 proto kernel scope link\n"
            if cmd[:2] == ["ip", "route"] else "",
        )
        report = validate_config_file(write_config(), check_hardware=True)
        assert any("overlaps" in i.message for i in report.issues)

    def test_non_colliding_route_table_is_silent(self, write_config, monkeypatch):
        from wilab.network import commands as commands_mod

        monkeypatch.setattr(
            commands_mod, "execute_command",
            lambda cmd, **kw: "10.0.0.0/8 dev eth0 proto kernel scope link\n"
            if cmd[:2] == ["ip", "route"] else "",
        )
        report = validate_config_file(write_config(), check_hardware=True)
        assert not any("overlaps" in i.message for i in report.issues)


# ==================================================================================================
# Rendering and secret safety
# ==================================================================================================


class TestRendering:
    def test_failed_report_contains_path_message_and_hint(self, write_config):
        text = validate_config_file(write_config({"min_timeout": 5})).render()
        assert "FAILED" in text
        assert "min_timeout" in text
        assert "→" in text

    def test_ok_report_mentions_networks_and_capabilities(self, write_config):
        text = validate_config_file(write_config()).render()
        assert "OK" in text
        assert "1 network(s)" in text
        assert "2.4ghz" in text

    def test_ok_with_warnings(self, write_config):
        report = validate_config_file(write_config({"api_port": 80}))
        assert report.ok is True
        assert "warning(s)" in report.render()

    def test_report_never_leaks_the_auth_token(self, write_config):
        """Review finding SYS-4: the report reaches journals and CI logs."""
        secret = "super-secret-value-9f3a"
        report = validate_config_file(write_config({
            "auth_token": secret,
            "min_timeout": 5,
        }))
        assert secret not in report.render()
        for issue in report.issues:
            assert secret not in issue.message
            assert secret not in (issue.hint or "")


class TestReportModel:
    def test_ok_is_true_with_warnings_only(self):
        report = ValidationReport("x", (ValidationIssue("a", "m", Severity.WARNING),))
        assert report.ok is True

    def test_ok_is_false_with_any_error(self):
        report = ValidationReport("x", (
            ValidationIssue("a", "m", Severity.WARNING),
            ValidationIssue("b", "m", Severity.ERROR),
        ))
        assert report.ok is False
        assert len(report.errors) == 1
        assert len(report.warnings) == 1
