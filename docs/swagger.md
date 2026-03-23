# Wi-Lab API Documentation

## Interactive API Documentation

Access interactive API testing and documentation at:

**Swagger UI:** `http://localhost:8080/docs`

**How to use:**
1. Open `http://localhost:8080/docs`
2. Click "Authorize" button (top-right)
3. Enter your `auth_token` from `config.yaml`
4. Test endpoints interactively

**Alternative formats:**
- ReDoc (read-only): `http://localhost:8080/redoc`
- OpenAPI JSON: `http://localhost:8080/openapi.json`

---

## Usage Guidance

- Use Swagger UI as the single source of truth for all available operations, schemas, and responses.
- Prefer interactive testing from Swagger instead of manual endpoint calls in shell snippets.
- Use the `Authorize` button once, then execute requests directly from the UI.

⚠️ **Note:** debug operations are expensive (150-600ms). Use them only for manual troubleshooting, not for frontend polling.

