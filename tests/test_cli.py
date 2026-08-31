"""Tests for the command-line interface (main.py).

``--validate-config`` must be safe to run on a production host at any moment: it reads a
file and prints a report, and does nothing else. Several tests below exist specifically to
keep it that way.

Covers TODOs/device-capabilities.md §12.3.
"""

import os

import pytest

import main as cli
from wilab.config import load_config


class TestArgumentParsing:
    def test_no_arguments_defaults_to_starting_the_server(self):
        args = cli.build_parser().parse_args([])
        assert args.validate_config is False
        assert args.config is None
        assert args.check_hardware is False

    def test_check_hardware_without_validate_is_accepted(self):
        """Harmless combination; rejecting it would only surprise someone scripting the CLI."""
        args = cli.build_parser().parse_args(["--check-hardware"])
        assert args.check_hardware is True
        assert args.validate_config is False

    def test_config_path_precedence(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "from-env.yaml"))
        assert cli.resolve_config_path(None).endswith("from-env.yaml")
        assert cli.resolve_config_path("/explicit.yaml") == "/explicit.yaml"

    def test_config_path_falls_back_to_cwd(self, monkeypatch):
        monkeypatch.delenv("CONFIG_PATH", raising=False)
        assert cli.resolve_config_path(None) == os.path.join(os.getcwd(), "config.yaml")


class TestExitCodes:
    def test_valid_config_exits_zero(self, write_config, capsys):
        assert cli.main(["--validate-config", "--config", write_config()]) == cli.EXIT_OK
        assert "OK" in capsys.readouterr().out

    def test_invalid_config_exits_one(self, write_config, capsys):
        path = write_config({"min_timeout": 5})
        assert cli.main(["--validate-config", "--config", path]) == cli.EXIT_INVALID
        out = capsys.readouterr().out
        assert "FAILED" in out
        assert "min_timeout" in out

    def test_missing_file_exits_two(self, tmp_path, capsys):
        """Distinct from exit 1 so CI can tell 'not mounted' from 'wrong'."""
        path = str(tmp_path / "absent.yaml")
        assert cli.main(["--validate-config", "--config", path]) == cli.EXIT_UNREADABLE
        assert "not found" in capsys.readouterr().out.lower()

    def test_malformed_yaml_exits_two(self, write_config, capsys):
        path = write_config(raw_text="auth_token: [oops\n  : :\n")
        assert cli.main(["--validate-config", "--config", path]) == cli.EXIT_UNREADABLE
        assert "Invalid YAML" in capsys.readouterr().out

    def test_warnings_alone_still_exit_zero(self, write_config, capsys):
        path = write_config({"cors_origins": ["http://localhost:4200"]})
        assert cli.main(["--validate-config", "--config", path]) == cli.EXIT_OK
        assert "warning" in capsys.readouterr().out.lower()

    def test_validate_uses_config_path_env_when_no_flag(self, write_config, monkeypatch):
        monkeypatch.setenv("CONFIG_PATH", write_config({"min_timeout": 5}))
        assert cli.main(["--validate-config"]) == cli.EXIT_INVALID


class TestValidateHasNoSideEffects:
    """The properties that make --validate-config safe to run on a live bench."""

    def test_never_starts_the_server(self, write_config, monkeypatch):
        import uvicorn

        started = []
        monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: started.append(True))
        cli.main(["--validate-config", "--config", write_config()])
        assert started == []

    def test_never_shells_out_without_check_hardware(self, write_config, monkeypatch):
        """Static validation must not touch the machine — that is what makes it portable."""
        from wilab.network import commands

        calls = []
        for name in ("execute_command", "execute_ip", "execute_iw", "execute_tc"):
            monkeypatch.setattr(
                commands, name,
                lambda *a, _n=name, **kw: (calls.append(_n), "")[1],
            )
        cli.main(["--validate-config", "--config", write_config()])
        assert calls == []

    def test_interfaces_untouched_without_check_hardware(self, write_config, monkeypatch):
        from wilab.wifi import interface as interface_mod

        seen = []
        monkeypatch.setattr(interface_mod, "validate_interface", lambda i: seen.append(i))
        cli.main(["--validate-config", "--config", write_config()])
        assert seen == []

    def test_check_hardware_verifies_the_interfaces(self, write_config, monkeypatch):
        from wilab.wifi import interface as interface_mod

        seen = []
        monkeypatch.setattr(interface_mod, "validate_interface", lambda i: seen.append(i))
        cli.main(["--validate-config", "--check-hardware", "--config", write_config()])
        assert seen == ["wls16"]

    def test_does_not_leave_config_path_behind(self, write_config, monkeypatch):
        """Only the startup path exports CONFIG_PATH for the dependency layer."""
        monkeypatch.delenv("CONFIG_PATH", raising=False)
        cli.main(["--validate-config", "--config", write_config()])
        assert "CONFIG_PATH" not in os.environ


class TestStartupEnforcement:
    """load_config is the single enforcement point; nothing can start against a bad file."""

    def test_load_config_raises_with_the_rendered_report(self, write_config):
        path = write_config({"country_code": "italy", "api_port": 0})
        with pytest.raises(SystemExit) as exc_info:
            load_config(path)
        message = str(exc_info.value)
        assert "FAILED" in message
        assert "country_code" in message
        assert "api_port" in message

    def test_capability_matrix_is_logged_at_startup(self, write_config, caplog):
        """The line that answers 'why did I get that antenna' in the journal."""
        import logging

        with caplog.at_level(logging.INFO, logger="wilab.config"):
            load_config(write_config())
        text = caplog.text
        assert "Managed device capabilities" in text
        assert "wls16" in text
        assert "2.4ghz" in text
