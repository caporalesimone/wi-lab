"""Device reservation endpoints (create, query, release)."""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...api.auth import maintenance_router as protected_router
from ...api.auth import require_token
from ...api.dependencies import get_config, get_reservation_manager
from ...api.errors import ApiErrorCode, domain_error
from ...config import AppConfig
from ...reservation import (
    DeviceRecoveryUnavailable,
    NoDeviceAvailableError,
    ReservationManager,
)
from ...timestamps import format_utc_timestamp
from .recovery_responses import (
    RETRY_AFTER_HEADER,
    RecoveryCode,
    recovery_error,
    recovery_example,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/device-reservation", tags=["Reservation"])
# Route tags add to the router's: a separate router keeps release-all only under
# Maintenance in Swagger. It is included before `router`, so `/all` is matched
# before `/{reservation_id}`. Token and X-Confirm-Password come from the router.
maintenance_router = protected_router(prefix="/device-reservation")


# ---- Request / Response models ----

class ReservationCreateRequest(BaseModel):
    # API-10: an unknown field is a 422, not ignored.
    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(
        ..., description="Reservation duration in seconds. 0 = unlimited, accepted only when "
        "`GET /status` reports `reservation_policy.allow_unlimited: true`; otherwise `422`.",
        json_schema_extra={"example": 3600}
    )

    @field_validator("duration_seconds")
    @classmethod
    def validate_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(
                "duration_seconds must be 0 (unlimited) or >= min_timeout"
            )
        return v


class ReservationResponse(BaseModel):
    reservation_id: str
    display_name: str
    interface: str
    expires_at: str | None = Field(
        None, description="Expiration timestamp in UTC (RFC 3339 with a Z suffix), null if unlimited",
        json_schema_extra={"format": "date-time", "examples": ["2026-11-19T23:00:00Z"]},
    )
    expires_in: int | None = Field(None, description="Seconds remaining until expiry, null if unlimited")


def _display_name_for(device_id: str, config: AppConfig) -> str:
    """Look up user-facing display name from config."""
    for n in config.antennas:
        if n.device_id == device_id:
            return n.display_name
    return device_id


# ---- Endpoints ----

@router.post(
    "",
    summary="Reserve an available Wi-Fi adapter",
    response_model=ReservationResponse,
    responses={
        200: {"description": "Device reserved successfully"},
        401: {"description": "Unauthorized"},
        409: {
            "description": "No adapter available. next_available_at is UTC, or null when no release is scheduled.",
            "content": {"application/json": {"example": {"detail": domain_error(
                ApiErrorCode.NO_DEVICE_AVAILABLE, "No device available",
                next_available_at="2026-11-19T23:00:00Z", next_available_in=18,
            )}}},
        },
        503: {
            "description": "No allocatable adapter: recovery (1002), quarantine or no Wi-Fi adapter detected (1003), or cleanup failure.",
            "headers": RETRY_AFTER_HEADER,
            "content": {"application/json": {"examples": {
                "device_recovering": recovery_example(RecoveryCode.DEVICE_RECOVERING),
                "device_unavailable": recovery_example(RecoveryCode.DEVICE_UNAVAILABLE),
                "cleanup_failed": {"value": {"detail": domain_error(
                    ApiErrorCode.CLEANUP_FAILED, "Failed to clean up device wlan0",
                )}},
            }}},
        },
    },
)
def create_reservation(
    req: ReservationCreateRequest = Body(..., openapi_examples={
        "timed": {"summary": "Reserve for two minutes", "value": {"duration_seconds": 120}},
        "unlimited": {"summary": "Reserve until release (if allowed)", "value": {"duration_seconds": 0}},
    }),
    config: AppConfig = Depends(get_config),
    mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
):
    """Reserve the first available device for the given duration.

    An adapter in recovery or quarantine is excluded. If an alternative is
    available it can still be reserved. Otherwise **503 / 1002** tells callers
    to retry this reservation request after `Retry-After`, not to reuse an old
    reservation ID. **503 / 1003** (every adapter quarantined, or no AP-capable
    adapter detected yet) has no automatic retry recommendation.
    """
    # Validate duration against config bounds
    duration = req.duration_seconds
    if duration == 0:
        if not config.allow_unlimited_reservation:
            raise HTTPException(
                status_code=422,
                detail="Unlimited reservations are not allowed (allow_unlimited_reservation is false)",
            )
    else:
        if duration < config.min_timeout:
            raise HTTPException(
                status_code=422,
                detail=f"duration_seconds must be at least {config.min_timeout} seconds",
            )
        if duration > config.max_timeout:
            raise HTTPException(
                status_code=422,
                detail=f"duration_seconds must be at most {config.max_timeout} seconds",
            )

    try:
        r = mgr.create(duration)
    except DeviceRecoveryUnavailable as exc:
        if exc.recovering:
            raise recovery_error(RecoveryCode.DEVICE_RECOVERING, retry_after=10) from exc
        raise recovery_error(RecoveryCode.DEVICE_UNAVAILABLE) from exc
    except NoDeviceAvailableError as exc:
        raise HTTPException(
            status_code=409,
            detail=domain_error(
                ApiErrorCode.NO_DEVICE_AVAILABLE, "No device available",
                next_available_at=format_utc_timestamp(exc.next_available_at),
                next_available_in=exc.next_available_in,
            ),
        )

    return _build_response(r, config)


def _build_response(r, config: AppConfig) -> ReservationResponse:
    """Build ReservationResponse handling unlimited (expires_at=None)."""
    return ReservationResponse(
        reservation_id=r.reservation_id,
        display_name=_display_name_for(r.device_id, config),
        interface=r.device_id,
        expires_at=format_utc_timestamp(r.expires_at),
        expires_in=r.expires_in,
    )


@maintenance_router.delete(
    "/all",
    summary="Release ALL reservations (maintenance only)",
    responses={
        200: {"description": "All reservations released"},
        503: {"description": "Cleanup failed; remaining reservations are still held"},
    },
)
def delete_all_reservations(
    mgr: ReservationManager = Depends(get_reservation_manager),
):
    """Release **all** active reservations, including those held by other clients.

    Maintenance and unblocking endpoint: clients must not use it, and it may be
    removed in a future version. It requires the `X-Confirm-Password` header,
    matching `protected_commands_password` in the server configuration; without
    that setting the endpoint is disabled (`403`).

    This is not atomic across adapters. If cleanup fails, earlier releases may
    already have completed. Inspect status and resolve the failure before retrying.
    """
    count = mgr.delete_all()
    return {"detail": f"{count} reservation(s) released", "released": count}


@router.get(
    "/{reservation_id}",
    response_model=ReservationResponse,
    responses={
        200: {"description": "Reservation details"},
        401: {"description": "Unauthorized"},
        404: {"description": "Reservation not found or expired"},
        503: {"description": "The expired device could not be cleaned up"},
    },
)
def get_reservation(
    reservation_id: str = Path(...),
    config: AppConfig = Depends(get_config),
    mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
):
    """Get current reservation status by token."""
    r = mgr.get(reservation_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Reservation not found or expired")

    return _build_response(r, config)


@router.delete(
    "/{reservation_id}",
    responses={
        200: {"description": "Reservation released"},
        401: {"description": "Unauthorized"},
        404: {"description": "Reservation not found or already expired"},
        503: {"description": "The device could not be cleaned up; the reservation remains held"},
    },
)
def delete_reservation(
    reservation_id: str = Path(...),
    mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
):
    """Release a reservation, stop any network and clean up before freeing the device.

    An explicit network stop is not required. For `503 / 1004`,
    the device stays held; retry release after the cleanup issue is resolved.
    For `404`, stop using the ID.
    """
    removed = mgr.delete(reservation_id)
    if not removed:
        raise HTTPException(
            status_code=404, detail="Reservation not found or already expired"
        )
    return {"detail": "Reservation released"}
