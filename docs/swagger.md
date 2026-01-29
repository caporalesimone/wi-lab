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
- OpenAPI YAML: `http://localhost:8080/openapi.yaml`

---

## Common Endpoints

### Health Check (No Auth)
```bash
curl http://localhost:8080/api/v1/health
```

### Debug Information (Requires Auth)
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/v1/debug
```

⚠️ **WARNING:** Debug endpoint is expensive (150-600ms). Use only for manual troubleshooting, not for frontend polling.

---

## All endpoint details available in Swagger UI at `http://localhost:8080/docs`

