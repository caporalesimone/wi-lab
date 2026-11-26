"""HTTP answers shared by several routes: antennas recovering or unavailable, adapter busy."""

from fastapi import HTTPException

from ..errors import ApiErrorCode, domain_error

_MESSAGES = {
    ApiErrorCode.DEVICE_RECOVERING: "Every free antenna is recovering; retry after Retry-After",
    ApiErrorCode.DEVICE_UNAVAILABLE: "No antenna is usable; check GET /status",
}


def recovery_error(code: ApiErrorCode, *, retry_after: int | None = None) -> HTTPException:
    """503 / 1002 or 1003 on a reservation: no antenna can be given now."""
    return HTTPException(
        status_code=503,
        detail=domain_error(code, _MESSAGES[code]),
        headers={"Retry-After": str(retry_after)} if retry_after is not None else None,
    )


def recovery_example(code: ApiErrorCode) -> dict:
    return {"value": {"detail": domain_error(code, _MESSAGES[code])}}


def device_busy_detail() -> dict:
    """Body of a 503 / 1006: another operation on the adapter is still running (RACE-1)."""
    return domain_error(
        ApiErrorCode.DEVICE_BUSY, "Another operation on this adapter is still running; retry after Retry-After",
    )


DEVICE_BUSY_RESPONSE = {
    "description": (
        "`detail.code: 1006` (`device_busy`): another operation on the same adapter, such "
        "as a network start (up to about 40 s, several minutes on a DFS channel), still held it after 5 s. "
        "Nothing was changed. Repeat the same request after `Retry-After` (2 s)."
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
    }}},
}


NETWORK_NOT_ACTIVE_EXAMPLE = {"detail": {
    "code": 1007, "reason": "network_not_active", "message": "Network wlan0 is not active",
}}

STOP_INCOMPLETE_EXAMPLE = {"detail": {
    "code": 1012, "reason": "stop_incomplete",
    "message": "The stop of the network on wlan0 did not complete: repeat DELETE .../network first",
}}

NETWORK_NOT_ACTIVE_RESPONSE = {
    "description": (
        "`detail.code: 1007` (`network_not_active`): the reservation is valid but has no "
        "running network. Create one first. `detail.code: 1012` (`stop_incomplete`): the "
        "last `DELETE .../network` did not complete and the network is half stopped; repeat "
        "the DELETE. A `404` instead always means the reservation itself is unknown, "
        "expired or invalidated."
    ),
    "content": {"application/json": {"examples": {
        "network_not_active": {"summary": "1007 - no running network", "value": NETWORK_NOT_ACTIVE_EXAMPLE},
        "stop_incomplete": {"summary": "1012 - half-stopped network, repeat the DELETE", "value": STOP_INCOMPLETE_EXAMPLE},
    }}},
}


def require_stop_complete(manager, device_id: str) -> None:
    """409 / 1012 while the client's last stop of the network did not complete (REV-9).

    The network is still in the manager's active list, but half stopped: Internet,
    TX power and QoS must not act on it.
    """
    if manager.stop_failed(device_id):
        raise HTTPException(status_code=409, detail=domain_error(
            ApiErrorCode.STOP_INCOMPLETE,
            f"The stop of the network on {device_id} did not complete: repeat DELETE .../network first",
        ))


RETRY_AFTER_HEADER = {
    "Retry-After": {
        "description": "Minimum wait in seconds. Absent for a terminal failure.",
        "schema": {"type": "integer", "minimum": 1},
        "example": 5,
    }
}
