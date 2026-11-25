import json
import zipfile

import pytest

from scripts import export_api_docs


def test_dereference_handles_nested_and_sibling_fields():
    schema = {"components": {"schemas": {"X": {"type": "string"}}}}
    node = {"$ref": "#/components/schemas/X", "description": "local"}
    assert export_api_docs.dereference(node, schema) == {"type": "string", "description": "local"}
    assert "$ref" in node


def test_dereference_rejects_cycles_and_external_references():
    schema = {"x": {"$ref": "#/x"}}
    with pytest.raises(ValueError, match="Circular"):
        export_api_docs.dereference(schema, schema)
    with pytest.raises(ValueError, match="external"):
        export_api_docs.dereference({"$ref": "https://example.test/x"}, schema)


def test_bundle_contains_current_schema_and_safe_embedded_docs(tmp_path, monkeypatch):
    schema = export_api_docs.build_schema()
    monkeypatch.setattr(export_api_docs, "fetch", lambda url: 'var x="</script>";' if url.endswith(".js") else "body{}")
    monkeypatch.setattr(export_api_docs, "build_schema", lambda: schema)
    assert export_api_docs.main(["--out", str(tmp_path)]) == 0
    archive = next(tmp_path.glob("wi-lab-api-docs-*.zip"))
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {"openapi.json", "swagger.html", "redoc.html"}
        assert json.loads(bundle.read("openapi.json")) == schema
        swagger = bundle.read("swagger.html").decode()
        redoc = bundle.read("redoc.html").decode()
    assert '"/api/v2/status"' in swagger
    assert '"$ref"' not in swagger
    assert "<\\/script>" in swagger
    assert "supportedSubmitMethods:[]" in swagger
    assert "disableGoogleFont:true" in redoc
