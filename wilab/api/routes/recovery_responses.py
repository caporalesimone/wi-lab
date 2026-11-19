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
    if code == RecoveryCode.RETRY_LATER:
        status_code = 409
    elif code == RecoveryCode.DEVICE_UNAVAILABLE and invalidated:
        status_code = 500
    else:
        status_code = 503
    return HTTPException(
        status_code=status_code,
        detail=_detail(code, invalidated),
        headers={"Retry-After": str(retry_after)} if retry_after is not None else None,
    )


def recovery_example(code: RecoveryCode, *, invalidated: bool = False) -> dict:
    return {"value": {"detail": _detail(code, invalidated)}}


RETRY_AFTER_HEADER = {
    "Retry-After": {
        "description": "Minimum wait in seconds. Absent for a terminal failure.",
        "schema": {"type": "integer", "minimum": 1},
        "example": 5,
    }
}
