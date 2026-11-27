"""The Swagger UI page (`/docs`), with the secrets hidden in the request shown.

Swagger UI keeps the token typed in "Authorize" out of sight, but after
"Execute" its cURL box (and the request snippets) printed it in clear:
`-H 'Authorization: Bearer <token>'`, ready for a screenshot or a paste in a
chat. A small plugin masks `Authorization` and `X-Confirm-Password` in the
request Swagger UI *displays* (`requestFor`, `mutatedRequestFor`); the request
it sends is built elsewhere and keeps them. A copied cURL command therefore
needs the token put back by hand.

FastAPI's `get_swagger_ui_html` takes only JSON parameters, so the plugin is
added to its page here.
"""

from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

MASK = "********"
MASKED_HEADERS = ("authorization", "x-confirm-password")

# Wraps the two selectors the live response and the cURL box read. Header names
# are matched without case; for Authorization the scheme ("Bearer") stays visible.
MASK_PLUGIN_JS = """
<script>
window.WilabMaskSecrets = function () {
  var hidden = %(headers)s;
  function mask(request) {
    if (!request || !request.get || !request.get("headers")) return request;
    var out = request;
    request.get("headers").forEach(function (value, name) {
      if (hidden.indexOf(String(name).toLowerCase()) === -1) return;
      var text = String(value);
      var scheme = /^(\\S+\\s+)\\S/.exec(text);
      out = out.setIn(["headers", name], (scheme && String(name).toLowerCase() === "authorization" ? scheme[1] : "") + "%(mask)s");
    });
    return out;
  }
  // Swagger UI calls a wrapped selector with (state, ...args); the original is
  // already bound to the state, so it takes only the args (path, method).
  function wrap(original) {
    return function (state, path, method) { return mask(original(path, method)); };
  }
  return {statePlugins: {spec: {wrapSelectors: {requestFor: wrap, mutatedRequestFor: wrap}}}};
};
</script>
""" % {"headers": str(list(MASKED_HEADERS)).replace("'", '"'), "mask": MASK}


def swagger_ui_page(openapi_url: str, title: str) -> HTMLResponse:
    """FastAPI's Swagger UI page with the masking plugin."""
    page = get_swagger_ui_html(openapi_url=openapi_url, title=f"{title} - Swagger UI")
    html = bytes(page.body).decode()
    bundle_end = html.index("</script>", html.index("swagger-ui-bundle.js")) + len("</script>")
    html = html[:bundle_end] + MASK_PLUGIN_JS + html[bundle_end:]
    # Our plugin next to Swagger UI's own (plugins add to the core ones).
    html = html.replace("presets: [", "plugins: [WilabMaskSecrets],\n    presets: [", 1)
    return HTMLResponse(html)
