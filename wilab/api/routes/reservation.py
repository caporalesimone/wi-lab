"""Device reservation endpoints (create, query, release)."""

from datetime import datetime, timezone

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, field_validator

from ...api.auth import require_token
from ...api.dependencies import get_config, get_reservation_manager
from ...config import AppConfig
from ...reservation import ReservationManager, NoDeviceAvailableError

router = APIRouter(prefix="/device-reservation", tags=["Reservation"])


# ---- Request / Response models ----

class ReservationCreateRequest(BaseModel):
    duration_seconds: int = Field(
        ..., description="Reservation duration in seconds (0 = unlimited, if allowed by config)",
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
    expires_at: Optional[str] = Field(None, description="Expiration datetime (yyyy-mm-dd HH:MM:SS), null if unlimited")
    expires_in: Optional[int] = Field(None, description="Seconds remaining until expiry, null if unlimited")


def _display_name_for(device_id: str, config: AppConfig) -> str:
    """Look up user-facing display name from config."""
    for n in config.networks:
        if n.device_id == device_id:
            return n.display_name
    return device_id


# ---- Endpoints ----

@router.post(
    "",
    response_model=ReservationResponse,
    responses={
        200: {"description": "Device reserved successfully"},
        401: {"description": "Unauthorized"},
        409: {"description": "All devices are currently reserved"},
    },
)
async def create_reservation(
    req: ReservationCreateRequest,
    config: AppConfig = Depends(get_config),
    mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
):
    """Reserve the first available device for the given duration."""
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
    except NoDeviceAvailableError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "No device available",
                "next_available_at": datetime.fromtimestamp(
                    exc.next_available_at
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "next_available_in": exc.next_available_in,
            },
        )

    return _build_response(r, config)


def _build_response(r, config: AppConfig) -> ReservationResponse:
    """Build ReservationResponse handling unlimited (expires_at=None)."""
    return ReservationResponse(
        reservation_id=r.reservation_id,
        display_name=_display_name_for(r.device_id, config),
        interface=r.device_id,
        expires_at=(
            datetime.fromtimestamp(r.expires_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            if r.expires_at is not None else None
        ),
        expires_in=r.expires_in,
    )


@router.get(
    "/{reservation_id}",
    response_model=ReservationResponse,
    responses={
        200: {"description": "Reservation details"},
        401: {"description": "Unauthorized"},
        404: {"description": "Reservation not found or expired"},
    },
)
async def get_reservation(
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
    },
)
async def delete_reservation(
    reservation_id: str = Path(...),
    mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
):
    """Release a reservation and free the device."""
    removed = mgr.delete(reservation_id)
    if not removed:
        raise HTTPException(
            status_code=404, detail="Reservation not found or already expired"
        )
    return {"detail": "Reservation released"}


@router.delete(
    "",
    responses={
        200: {"description": "All reservations released"},
        401: {"description": "Unauthorized"},
    },
)
async def delete_all_reservations(
    mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
):
    """Release all active reservations at once."""
    count = mgr.delete_all()
    return {"detail": f"{count} reservation(s) released", "released": count}
