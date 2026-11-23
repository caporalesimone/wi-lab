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
        ({"networks": ""}, "networks"),
    ],
)
def test_optional_config_validation_reports_errors_without_values(tmp_path, changes, message):
    config = {"auth_token": "private-token", "dhcp_base_network": "192.168.120.0/24", **changes}
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
        "networks:\n"
        "  - interface: wlan0\n"
        "    disable: true\n"
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
