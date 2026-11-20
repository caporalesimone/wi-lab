from unittest.mock import Mock

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
