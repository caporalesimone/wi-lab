from unittest.mock import Mock

import pytest

import main


def test_main_reuses_runtime_configuration(monkeypatch, config):
    loader = Mock(return_value=config)
    server = Mock()
    monkeypatch.setattr(main, "load_config", loader)
    monkeypatch.setattr(main, "log_host_impact_warning", lambda: None)
    monkeypatch.setattr(main, "run_prechecks", list)
    monkeypatch.setattr(main.uvicorn, "run", server)
    main.main()
    # The app's context runs on the configuration main loaded (ARCH-5).
    assert server.call_args.args[0].state.context.config is config
    loader.assert_called_once_with()


@pytest.mark.parametrize("port", [8080, 8123])
def test_main_listens_on_configured_port(monkeypatch, config, port):
    monkeypatch.setattr(config, "api_port", port)  # `config` is shared by the whole session
    server = Mock()
    monkeypatch.setattr(main, "load_config", lambda: config)
    monkeypatch.setattr(main, "log_host_impact_warning", lambda: None)
    monkeypatch.setattr(main, "run_prechecks", list)
    monkeypatch.setattr(main.uvicorn, "run", server)
    main.main()
    assert server.call_args.kwargs["port"] == port
