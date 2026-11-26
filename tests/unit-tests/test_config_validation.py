import subprocess
import sys

import pytest
import yaml

from wilab.config_validation import validate_config_file


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"api_port": 65536}, "api_port"),
        ({"min_timeout": 100, "max_timeout": 60}, "max_timeout"),
        ({"dns_server": "not-an-address"}, "dns_server"),
        ({"auth_token": "  "}, "auth_token"),
        ({"antennas": ""}, "antennas"),
    ],
)
def test_optional_config_validation_reports_errors_without_values(tmp_path, changes, message):
    config = {"auth_token": "private-token", "dhcp_base_network": "192.168.120.0/24", "dns_server": "8.8.8.8", **changes}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    errors, warnings = validate_config_file(str(path))
    assert any(message in error for error in errors)
    assert "private-token" not in repr((errors, warnings))


def test_config_validation_warns_about_ignored_fields_and_example_token(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "auth_token: secret-token-12345\n"
        "dhcp_base_network: 192.168.120.0/24\n"
        "dns_server: 8.8.8.8\n"
        "antennas:\n"
        "  - interface: wlan0\n"
        "    disable: true\n"
        "    show_dfs: false\n"
        "    capabilities: [5ghz]\n"
        "    usb_recovery_port: legacy\n"
    )
    errors, warnings = validate_config_file(str(path))
    assert not errors
    assert any("example" in warning for warning in warnings)
    assert any("capabilities" in warning for warning in warnings)
    assert any("usb_recovery_port" in warning for warning in warnings)


def test_validation_cli_does_not_start_service_or_print_secrets(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("auth_token: private-token\ndhcp_base_network: 192.168.120.0/24\napi_port: 0\n")
    result = subprocess.run(
        [sys.executable, "main.py", "--validate-config", "--config", str(path)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 1
    assert "api_port" in result.stdout
    assert "private-token" not in result.stdout + result.stderr
    assert "starting" not in result.stderr.lower()


def test_malformed_yaml_does_not_echo_input(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("auth_token: private-token\nbroken: [")
    errors, _ = validate_config_file(str(path))
    assert errors
    assert "private-token" not in repr(errors)


# T-15 (BUG-3): `--validate-config` and the service startup give the same verdict.
_PARITY_CASES = [
    {},
    {"api_port": 0},
    {"api_port": 65536},
    {"min_timeout": 100, "max_timeout": 60},
    {"max_timeout": 0},
    {"dns_server": "foo"},
    {"auth_token": "   "},
    {"antennas": ""},
    {"antennas": [{"interface": "wlan0", "display_name": "A"}]},     # show_dfs missing
    {"dhcp_base_network": "10.20.0.0/16"},
    {"country_code": "EU"},
    {"antennas": [{"interface": "wlan0", "disable": True, "show_dfs": False, "usb_recovery_port": "1-1"}]},
]


@pytest.mark.parametrize("changes", _PARITY_CASES)
def test_offline_validation_and_startup_agree(tmp_path, changes):
    from wilab.config import load_config

    config = {"auth_token": "private-token", "dhcp_base_network": "192.168.120.0/24", "dns_server": "8.8.8.8", **changes}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    errors, _ = validate_config_file(str(path))
    try:
        load_config(str(path))
        started = True
    except SystemExit:
        started = False
    assert started == (not errors), errors


def test_startup_refuses_an_invalid_dns_server(tmp_path):
    from wilab.config import load_config

    path = tmp_path / "config.yaml"
    path.write_text("auth_token: t\ndhcp_base_network: 192.168.120.0/24\ndns_server: foo\n")
    with pytest.raises(SystemExit, match="dns_server"):
        load_config(str(path))


def test_startup_refuses_a_config_without_dns_server(tmp_path):
    """NET-8: no default DNS server; the service says which key is missing."""
    from wilab.config import load_config

    path = tmp_path / "config.yaml"
    path.write_text("auth_token: t\ndhcp_base_network: 192.168.120.0/24\n")
    with pytest.raises(SystemExit, match="dns_server"):
        load_config(str(path))
    errors, _ = validate_config_file(str(path))
    assert any("dns_server" in error for error in errors)


def test_model_errors_name_the_fields_without_values(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("auth_token: private-token\ndhcp_base_network: 192.168.120.0/24\ndns_server: 8.8.8.8\n"
                    "min_timeout: 100\nmax_timeout: 60\n")
    errors, _ = validate_config_file(str(path))
    assert errors == ["Invalid configuration: Value error, max_timeout must be positive and at least min_timeout"]


def test_every_antenna_entry_states_show_dfs(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("auth_token: t\ndhcp_base_network: 192.168.120.0/24\ndns_server: 8.8.8.8\n"
                    "antennas:\n  - interface: wlan0\n    disable: true\n")
    errors, _ = validate_config_file(str(path))
    assert errors == ["Invalid configuration field: antennas"]
