"""Device reservation endpoints (create, query, release)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from ...api.auth import require_token
from ...api.dependencies import get_reservation_manager
from ...reservation import ReservationManager

router = APIRouter(prefix="/device-reservation", tags=["Reservation"])


# ---- Request / Response models ----

class ReservationCreateRequest(BaseModel):
    duration_seconds: int = Field(
        ..., gt=0, description="Reservation duration in seconds"
    )


class ReservationResponse(BaseModel):
    reservation_id: str
    device_id: str
    expires_at: str = Field(description="Expiration datetime (yyyy-mm-dd HH:MM:SS)")
    expires_in: int = Field(description="Seconds remaining until expiry")


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
    mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
):
    """Reserve the first available device for the given duration."""
    try:
        r = mgr.create(req.duration_seconds)
    except ValueError:
        raise HTTPException(status_code=409, detail="No device available")

    return ReservationResponse(
        reservation_id=r.reservation_id,
        device_id=r.device_id,
        expires_at=datetime.fromtimestamp(r.expires_at).strftime("%Y-%m-%d %H:%M:%S"),
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
    mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
):
    """Get current reservation status by token."""
    r = mgr.get(reservation_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Reservation not found or expired")

    return ReservationResponse(
        reservation_id=r.reservation_id,
        device_id=r.device_id,
        expires_at=datetime.fromtimestamp(r.expires_at).strftime("%Y-%m-%d %H:%M:%S"),
        expires_in=r.expires_in,
    )


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
