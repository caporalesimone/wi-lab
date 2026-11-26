"""Shared runtime and OpenAPI representation of API failures."""

import copy
import logging
from collections.abc import Mapping
from enum import IntEnum
from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ApiErrorCode(IntEnum):
    """Every domain code in `detail.code`, one enum for the whole range (REV-16).

    Every code is listed, with its HTTP status and client action, in
    docs/error-codes.md.
    """
    RETRY_LATER = 1001                 # no longer answered: the server retries radio failures itself
    DEVICE_RECOVERING = 1002
    DEVICE_UNAVAILABLE = 1003
    CLEANUP_FAILED = 1004              # no longer answered: the release always succeeds
    NO_DEVICE_AVAILABLE = 1005
    DEVICE_BUSY = 1006
    NETWORK_NOT_ACTIVE = 1007
    NETWORK_ALREADY_ACTIVE = 1008
    RESTORATION_IN_PROGRESS = 1009
    QOS_PROFILE_ALREADY_ACTIVE = 1010
    QOS_PROFILE_NOT_ACTIVE = 1011
    STOP_INCOMPLETE = 1012
    STARTUP_FAILED = 1013

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


GONE_REASONS = {
    "reservation_released": "released (by its owner or by release-all)",
    "reservation_expired": "expired, also when it would expire before the next AP start",
    "reservation_invalidated": "invalidated: its antenna was quarantined",
    "reservation_not_found": "never existed, or ended more than an hour ago",
}

_GONE_RESPONSE = {
    "description": (
        "The reservation ID is no longer valid. `detail.reason` is stable and says why: "
        + "; ".join(f"`{reason}`: {text}" for reason, text in GONE_REASONS.items())
        + ". After `reservation_invalidated` or `reservation_expired` reserve again; after "
        "`reservation_released` or `reservation_not_found` there is nothing to release."
    ),
    "content": {"application/json": {"examples": {
        reason: {"value": {"detail": {"code": 404, "reason": reason, "message": text}}}
        for reason, text in GONE_REASONS.items()
    }}},
}


def document_errors(paths: dict[str, Any]) -> None:
    """Document the same envelope for explicit and framework-generated errors."""
    for path, path_item in paths.items():
        if not path.startswith("/api/v2/"):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            responses.setdefault("500", {"description": "Internal server error"})
            if "{reservation_id}" in path:
                # Every call with an ID answers the same 404, with a stable reason.
                responses["404"] = copy.deepcopy(_GONE_RESPONSE)
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
                    return error_detail(http_status, detail)

                if "examples" in media:
                    for example in media["examples"].values():
                        if "value" in example:
                            example["value"]["detail"] = example_detail(example["value"]["detail"])
                else:
                    fallback = "field_name: validation error" if status_code == 422 else None
                    example = media.get("example", {"detail": fallback})
                    media["example"] = {"detail": example_detail(example["detail"])}
