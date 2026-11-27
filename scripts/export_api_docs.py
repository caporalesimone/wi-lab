#!/usr/bin/env python3
"""Export an offline API documentation bundle from the current application."""

import argparse
import html
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SWAGGER_JS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"
SWAGGER_CSS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css"
REDOC_JS = "https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js"


def build_schema() -> dict[str, Any]:
    from wilab.api import create_app
    from wilab.config import load_config

    config = load_config(str(ROOT / "config.example.yaml"))
    return create_app(config).openapi()


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8")


def dereference(node: Any, root: dict[str, Any], stack: tuple[str, ...] = ()) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if ref is not None:
            if not isinstance(ref, str) or not ref.startswith("#/"):
                raise ValueError(f"Cannot inline external reference: {ref}")
            if ref in stack:
                raise ValueError(f"Circular reference: {ref}")
            target: Any = root
            for part in ref[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            resolved = dereference(target, root, (*stack, ref))
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            if siblings:
                if not isinstance(resolved, dict):
                    raise ValueError(f"Cannot merge reference siblings: {ref}")
                resolved = {**resolved, **dereference(siblings, root, stack)}
            return resolved
        return {key: dereference(value, root, stack) for key, value in node.items()}
    if isinstance(node, list):
        return [dereference(value, root, stack) for value in node]
    return node


def script_safe(text: str) -> str:
    return re.sub(r"</(script)", lambda match: "<\\/" + match.group(1), text, flags=re.IGNORECASE)


def render_docs(schema: dict[str, Any]) -> dict[str, str]:
    swagger_js = fetch(SWAGGER_JS)
    swagger_css = fetch(SWAGGER_CSS)
    redoc_js = fetch(REDOC_JS)
    if re.search(r"</style", swagger_css, re.IGNORECASE):
        raise ValueError("Cannot safely inline Swagger stylesheet")
    title = html.escape(schema["info"]["title"])
    spec = json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")
    swagger_spec = json.dumps(dereference(schema, schema), ensure_ascii=False).replace("</", "<\\/")
    swagger = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title} - Swagger UI</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>{swagger_css}</style></head>
<body><div id="swagger-ui"></div><script>{script_safe(swagger_js)}</script>
<script>SwaggerUIBundle({{spec:{swagger_spec},dom_id:"#swagger-ui",deepLinking:true,
supportedSubmitMethods:[],presets:[SwaggerUIBundle.presets.apis]}});</script></body></html>"""
    redoc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title} - ReDoc</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><div id="redoc"></div><script>{script_safe(redoc_js)}</script>
<script>Redoc.init({spec},{{disableGoogleFont:true}},document.getElementById("redoc"));</script></body></html>"""
    return {
        "openapi.json": json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        "swagger.html": swagger,
        "redoc.html": redoc,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="api-docs", help="output directory")
    args = parser.parse_args(argv)
    schema = build_schema()
    files = render_docs(schema)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")
    archive = out / f"wi-lab-api-docs-{schema['info']['version']}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in files:
            bundle.write(out / name, arcname=name)
    print(f"API documentation written to {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
