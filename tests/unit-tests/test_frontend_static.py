"""T-01 (SEC-1): the frontend route never serves a file outside the frontend directory.

The route function is called directly: an HTTP client normalises `..` and `//`
before sending, so it would never reach the cases an attacker sends with
`curl --path-as-is`.
"""

import asyncio

import pytest
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from wilab import api as api_module
from wilab.api import create_app


@pytest.fixture
def frontend(tmp_path, monkeypatch):
    root = tmp_path / "root"
    app_dir = root / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "index.html").write_text("<html>frontend</html>")
    (app_dir / "main.js").write_text("console.log('ok')")
    secret = root / "secret.txt"
    secret.write_text("auth_token: do-not-leak")
    monkeypatch.setattr(api_module, "_candidate_frontend_paths", lambda: [app_dir])
    app = create_app()
    route = next(r for r in app.routes if getattr(r, "path", None) == "/{full_path:path}")
    return route.endpoint, app_dir.resolve(), secret.resolve()


def _serve(endpoint, full_path: str):
    return asyncio.run(endpoint(full_path))


@pytest.mark.parametrize("make_path", [
    lambda secret: "../secret.txt",
    lambda secret: str(secret),
    lambda secret: "/" + str(secret),
    lambda secret: "app/../../secret.txt",
    lambda secret: "/etc/hostname",
])
def test_a_path_outside_the_frontend_is_never_served(frontend, make_path):
    endpoint, app_dir, secret = frontend
    try:
        response = _serve(endpoint, make_path(secret))
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        return
    # The SPA fallback is allowed; the secret (or any host file) is not.
    assert isinstance(response, FileResponse)
    assert str(response.path) == str(app_dir / "index.html")


def test_a_frontend_file_is_served(frontend):
    endpoint, app_dir, _secret = frontend
    assert str(_serve(endpoint, "index.html").path) == str(app_dir / "index.html")
    assert str(_serve(endpoint, "main.js").path) == str(app_dir / "main.js")


def test_an_unknown_frontend_path_falls_back_to_the_page(frontend):
    endpoint, app_dir, _secret = frontend
    assert str(_serve(endpoint, "reservations/abc").path) == str(app_dir / "index.html")


@pytest.mark.parametrize("path", ["docs/oauth2-redirect", "redoc/x", "openapi.json"])
def test_documentation_paths_are_not_the_frontend(frontend, path):
    """They used to answer 200 with a body `null`."""
    endpoint, _app_dir, _secret = frontend
    with pytest.raises(StarletteHTTPException) as exc:
        _serve(endpoint, path)
    assert exc.value.status_code == 404
