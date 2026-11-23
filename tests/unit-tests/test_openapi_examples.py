"""API-9 / T-16: every 200 example in the OpenAPI schema matches its response model."""

from typing import Any

import pytest
from pydantic import BaseModel

from wilab.api import create_app


def _examples(response: dict) -> list[Any]:
    media = response.get("content", {}).get("application/json", {})
    found = [media["example"]] if "example" in media else []
    found += [entry["value"] for entry in media.get("examples", {}).values() if "value" in entry]
    return found


def _unknown_keys(model: type[BaseModel], value: Any, path: str = "") -> list[str]:
    """Keys the model does not declare (Pydantic ignores them silently)."""
    if not isinstance(value, dict):
        return []
    known = {info.alias or name for name, info in model.model_fields.items()} | set(model.model_fields)
    unknown = [f"{path}{key}" for key in value if key not in known]
    for name, info in model.model_fields.items():
        annotation = info.annotation
        nested = next(
            (t for t in getattr(annotation, "__args__", (annotation,))
             if isinstance(t, type) and issubclass(t, BaseModel)),
            None,
        )
        if nested is not None and isinstance(value.get(name), dict):
            unknown += _unknown_keys(nested, value[name], f"{path}{name}.")
    return unknown


def _model(name: str) -> type[BaseModel] | None:
    import importlib
    import pkgutil

    import wilab.api.routes as routes
    import wilab.models as models

    modules = [models] + [
        importlib.import_module(f"wilab.api.routes.{m.name}") for m in pkgutil.iter_modules(routes.__path__)
    ]
    for module in modules:
        candidate = getattr(module, name, None)
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


def _cases() -> list[tuple[str, type[BaseModel], Any]]:
    schema = create_app().openapi()
    cases = []
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            ok = operation.get("responses", {}).get("200", {})
            ref = ok.get("content", {}).get("application/json", {}).get("schema", {}).get("$ref", "")
            model = _model(ref.rsplit("/", 1)[-1]) if ref else None
            if model is None:
                continue
            for value in _examples(ok):
                cases.append((f"{method.upper()} {path}", model, value))
    return cases


CASES = _cases()


def test_there_are_examples_to_check():
    assert len(CASES) >= 8


@pytest.mark.parametrize(("operation", "model", "example"), CASES, ids=[c[0] for c in CASES])
def test_200_example_matches_the_response_model(operation, model, example):
    model.model_validate(example)
    assert _unknown_keys(model, example) == [], f"{operation}: example has fields the model lacks"


def test_examples_are_not_patched_in_by_custom_openapi():
    """custom_openapi only adds the shared error envelope (no silent try/except)."""
    import inspect

    import wilab.api as api

    source = inspect.getsource(api.create_app)
    assert "except Exception:\n            # If schema structure changes" not in source
    assert '"device_id": "wls16"' not in source
