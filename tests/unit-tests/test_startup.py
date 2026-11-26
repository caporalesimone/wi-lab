from unittest.mock import Mock

import pytest

import main
from wilab.api import dependencies


def test_main_reuses_runtime_configuration(monkeypatch, config):
    loader = Mock(return_value=config)
    monkeypatch.setattr(dependencies, "_config", None)
    monkeypatch.setattr(dependencies, "load_config", loader)
    monkeypatch.setattr(main, "log_host_impact_warning", lambda: None)
    monkeypatch.setattr(main, "check_existing_wilab_rules", lambda: None)
    monkeypatch.setattr(main.uvicorn, "run", lambda *args, **kwargs: None)
    main.main()
    assert dependencies.get_config() is config
    loader.assert_called_once_with()


@pytest.mark.parametrize("port", [8080, 8123])
def test_main_listens_on_configured_port(monkeypatch, config, port):
    monkeypatch.setattr(config, "api_port", port)  # `config` is shared by the whole session
    server = Mock()
    monkeypatch.setattr(main, "get_config", lambda: config)
    monkeypatch.setattr(main, "log_host_impact_warning", lambda: None)
    monkeypatch.setattr(main, "check_existing_wilab_rules", lambda: None)
    monkeypatch.setattr(main.uvicorn, "run", server)
    main.main()
    assert server.call_args.kwargs["port"] == port
