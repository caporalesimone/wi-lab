"""HTTP contract for network creation recovery."""

from enum import IntEnum

from fastapi import HTTPException


class RecoveryCode(IntEnum):
    RETRY_LATER = 1001
    DEVICE_RECOVERING = 1002
    DEVICE_UNAVAILABLE = 1003


def _detail(code: RecoveryCode, invalidated: bool) -> dict:
    return {
        "code": int(code),
        "reason": code.name.lower(),
        "reservation_invalidated": invalidated,
    }


def recovery_error(
    code: RecoveryCode, *, invalidated: bool = False, retry_after: int | None = None,
) -> HTTPException:
    # 1003 with reservation_invalidated is a state of the client's reservation, not a
    # server defect: 503, never 500, which clients and proxies treat as retryable (API-4).
    status_code = 409 if code == RecoveryCode.RETRY_LATER else 503
    return HTTPException(
        status_code=status_code,
        detail=_detail(code, invalidated),
        headers={"Retry-After": str(retry_after)} if retry_after is not None else None,
    )


def recovery_example(code: RecoveryCode, *, invalidated: bool = False) -> dict:
    return {"value": {"detail": _detail(code, invalidated)}}


def device_busy_detail() -> dict:
    """Body of a 503 / 1006: another operation on the adapter is still running (RACE-1)."""
    return {
        "code": 1006,
        "reason": "device_busy",
        "message": "Another operation on this adapter is still running; retry after Retry-After",
    }


DEVICE_BUSY_RESPONSE = {
    "description": (
        "`detail.code: 1006` (`device_busy`): another operation on the same adapter, such "
        "as a network start (up to 20 s, 75 s on a DFS channel), still held it after 5 s. "
        "Nothing was changed. Repeat the same request after `Retry-After` (2 s). "
        "`detail.code: 1004` (`cleanup_failed`): a device cleanup failed; do not retry "
        "blindly, check `GET /api/v1/status`."
    ),
    "headers": {
        "Retry-After": {
            "description": "Seconds to wait before repeating the request. Present with `1006` only.",
            "schema": {"type": "integer", "minimum": 1},
            "example": 2,
        },
    },
    "content": {"application/json": {"examples": {
        "device_busy": {"summary": "1006 - adapter busy, retry", "value": {"detail": device_busy_detail()}},
        "cleanup_failed": {"summary": "1004 - cleanup failed", "value": {"detail": {
            "code": 1004, "reason": "cleanup_failed", "message": "Device cleanup failed",
        }}},
    }}},
}


RETRY_AFTER_HEADER = {
    "Retry-After": {
        "description": "Minimum wait in seconds. Absent for a terminal failure.",
        "schema": {"type": "integer", "minimum": 1},
        "example": 5,
    }
}
