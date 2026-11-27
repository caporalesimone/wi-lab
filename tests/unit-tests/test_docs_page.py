"""/docs masks the token in the request Swagger UI shows (cURL box, snippets)."""

from fastapi.testclient import TestClient

from wilab.api import create_app
from wilab.api.docs_page import MASKED_HEADERS


def test_docs_has_the_masking_plugin_before_swagger_starts():
    page = TestClient(create_app()).get("/docs")
    assert page.status_code == 200
    html = page.text
    plugin = html.index("window.WilabMaskSecrets = function")
    assert html.index("swagger-ui-bundle.js") < plugin < html.index("SwaggerUIBundle({")
    assert "plugins: [WilabMaskSecrets]" in html
    assert "requestFor: wrap, mutatedRequestFor: wrap" in html
    for header in MASKED_HEADERS:
        assert f'"{header}"' in html


def test_docs_is_not_in_the_schema_and_redoc_stays():
    client = TestClient(create_app())
    assert "/docs" not in client.get("/openapi.json").json()["paths"]
    assert client.get("/redoc").status_code == 200
