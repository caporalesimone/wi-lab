"""Shared runtime and OpenAPI representation of API failures."""

import logging
from collections.abc import Mapping
from enum import IntEnum
from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ApiErrorCode(IntEnum):
    CLEANUP_FAILED = 1004
    NO_DEVICE_AVAILABLE = 1005
    DEVICE_BUSY = 1006

# Seconds a client should wait before repeating a request answered 503 / 1006.
DEVICE_BUSY_RETRY_AFTER = 2


def error_detail(status_code: int, detail: Any) -> dict[str, Any]:
    """Keep domain codes; use the HTTP status as the code for other errors."""
    if isinstance(detail, dict) and "code" in detail:
        return detail
    try:
        status = HTTPStatus(status_code)
    except ValueError:
        status = None
    reason = status.name.lower() if status is not None else "http_error"
    if status_code == 422:
        reason = "validation_error"
    if isinstance(detail, dict):
        fields = detail.copy()
        message = fields.pop("error", None) or (status.phrase if status else "Request failed")
        return {"code": status_code, "reason": reason, "message": message, **fields}
    message = detail if isinstance(detail, str) else (status.phrase if status else "Request failed")
    return {"code": status_code, "reason": reason, "message": message}


def domain_error(code: ApiErrorCode, message: str, **fields: Any) -> dict[str, Any]:
    return {"code": code.value, "reason": code.name.lower(), "message": message, **fields}


def api_error_response(
    request: Request,
    status_code: int,
    detail: Any,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    payload = error_detail(status_code, detail)
    if 500 <= status_code < 600:
        operation = getattr(request.scope.get("route"), "name", None) or "unknown"
        logger.error(
            "API failure operation=%s http_status=%d detail_code=%d",
            operation, status_code, payload["code"],
        )
    return JSONResponse(status_code=status_code, headers=headers, content={"detail": payload})


def document_errors(paths: dict[str, Any]) -> None:
    """Document the same envelope for explicit and framework-generated errors."""
    for path, path_item in paths.items():
        if not path.startswith("/api/v1/"):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            responses.setdefault("500", {"description": "Internal server error"})
            for code, response in responses.items():
                if not code.isdigit() or not 400 <= int(code) <= 599:
                    continue
                status_code = int(code)
                media = response.setdefault("content", {}).setdefault("application/json", {})
                if media.get("schema", {}).get("$ref") == "#/components/schemas/HTTPValidationError":
                    media.pop("schema")
                media.setdefault("schema", {
                    "type": "object",
                    "required": ["detail"],
                    "properties": {"detail": {
                        "type": "object",
                        "required": ["code", "reason"],
                        "properties": {
                            "code": {"type": "integer"},
                            "reason": {"type": "string"},
                            "message": {"type": "string"},
                        },
                    }},
                })
                def example_detail(detail: Any, http_status: int = status_code) -> dict[str, Any]:
                    if http_status == 503 and not isinstance(detail, dict):
                        return domain_error(ApiErrorCode.CLEANUP_FAILED, detail or "Device cleanup failed")
                    return error_detail(http_status, detail)

                if "examples" in media:
                    for example in media["examples"].values():
                        if "value" in example:
                            example["value"]["detail"] = example_detail(example["value"]["detail"])
                else:
                    fallback = "field_name: validation error" if status_code == 422 else None
                    example = media.get("example", {"detail": fallback})
                    media["example"] = {"detail": example_detail(example["detail"])}
