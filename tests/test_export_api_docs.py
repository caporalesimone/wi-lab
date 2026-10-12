"""Tests for scripts/export_api_docs.py (the offline API documentation bundle)."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "export_api_docs.py"


@pytest.fixture(scope="module")
def export_api_docs():
    spec = importlib.util.spec_from_file_location("export_api_docs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDereference:
    SPEC = {
        "paths": {"/x": {"post": {"requestBody": {"schema": {"$ref": "#/components/schemas/A"}}}}},
        "components": {"schemas": {
            "A": {"type": "object", "properties": {"b": {"$ref": "#/components/schemas/B"}}},
            "B": {"type": "string"},
        }},
    }

    def test_nested_references_are_inlined(self, export_api_docs):
        flat = export_api_docs.dereference(self.SPEC, self.SPEC)
        body = flat["paths"]["/x"]["post"]["requestBody"]["schema"]
        assert body == {"type": "object", "properties": {"b": {"type": "string"}}}

    def test_input_is_not_modified(self, export_api_docs):
        before = json.dumps(self.SPEC)
        export_api_docs.dereference(self.SPEC, self.SPEC)
        assert json.dumps(self.SPEC) == before

    def test_circular_reference_is_refused_not_looped(self, export_api_docs):
        spec = {"components": {"schemas": {"N": {"properties": {"next": {"$ref": "#/components/schemas/N"}}}}}}
        with pytest.raises(ValueError, match="circular"):
            export_api_docs.dereference(spec, spec)

    def test_real_schema_has_no_reference_left(self, export_api_docs):
        """The Swagger page opened from disk cannot resolve '#/...' - none may remain."""
        schema = export_api_docs.build_schema()
        assert '"$ref"' in json.dumps(schema)            # the source still has them
        assert '"$ref"' not in json.dumps(export_api_docs.dereference(schema, schema))


class TestHtmlEscaping:
    def test_only_the_script_terminator_is_escaped_in_code(self, export_api_docs):
        code = 'var r=/</g; var s="</script>";'
        out = export_api_docs.js_safe(code)
        assert "/</g" in out                              # regex literal untouched
        assert "</script" not in out.lower()

    def test_json_cannot_close_the_script_element(self, export_api_docs):
        assert "</" not in export_api_docs.json_safe('{"a": "</script>"}')
