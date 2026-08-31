"""Device reservation endpoints (create, query, release)."""

import logging
from datetime import datetime, timezone

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, field_validator

from ...api.auth import require_token
from ...api.dependencies import get_config, get_manager, get_reservation_manager
from ...config import AppConfig, Capability, normalise_capability_id
from ...reservation import (
    CapabilityUnsatisfiableError,
    NoDeviceAvailableError,
    ReservationManager,
    UnknownDeviceError,
)
from ...wifi.manager import NetworkManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/device-reservation", tags=["Reservation"])


# ---- Request / Response models ----

class ReservationCreateRequest(BaseModel):
    duration_seconds: int = Field(
        ..., description="Reservation duration in seconds (0 = unlimited, if allowed by config)",
        json_schema_extra={"example": 3600}
    )
    required_capabilities: Optional[List[str]] = Field(
        default=None,
        description=(
            "Capabilities the assigned device must provide. When omitted or empty, any "
            "device is acceptable. Wi-Lab assigns the least capable matching free device, "
            "so scarce multi-band hardware stays available for requests that need it."
        ),
        json_schema_extra={"example": ["2.4ghz"]},
    )
    interface: Optional[str] = Field(
        default=None,
        description=(
            "Pin a specific managed device by interface name. When omitted, Wi-Lab "
            "selects the best match. May be combined with required_capabilities, which "
            "then act as a guard rail on the pinned device."
        ),
        json_schema_extra={"example": "wlxbc071dc527d6"},
    )

    @field_validator("duration_seconds")
    @classmethod
    def validate_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(
                "duration_seconds must be 0 (unlimited) or >= min_timeout"
            )
        return v

    @field_validator("required_capabilities")
    @classmethod
    def validate_capability_ids(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Canonicalise and validate ids against the same registry the config uses.

        Normalisation goes through the shared normalise_capability_id(), so the file and
        the wire cannot drift on "5GHz". The result is de-duplicated and sorted, which
        makes the endpoint independent of client-side ordering.
        """
        if v is None:
            return v
        canonical = [normalise_capability_id(c) for c in v]
        unknown = sorted({c for c in canonical if c not in Capability.ids()})
        if unknown:
            raise ValueError(
                f"Unknown capabilities: {', '.join(unknown)}. "
                f"Valid: {', '.join(Capability.ids())}"
            )
        return sorted(set(canonical))


class ReservationResponse(BaseModel):
    reservation_id: str
    display_name: str
    interface: str
    expires_at: Optional[str] = Field(None, description="Expiration datetime (yyyy-mm-dd HH:MM:SS), null if unlimited")
    expires_in: Optional[int] = Field(None, description="Seconds remaining until expiry, null if unlimited")
    capabilities: List[str] = Field(
        default_factory=list,
        description="Capabilities the assigned device provides. Lets a client know what "
                    "it actually got without cross-referencing /status.",
        json_schema_extra={"example": ["2.4ghz"]},
    )


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
        404: {"description": "The pinned interface is not managed by Wi-Lab"},
        409: {"description": "Matching devices exist but all are reserved (transient)"},
        422: {"description": "Invalid duration, unknown capability, or no device can "
                             "ever provide the requested capabilities (permanent)"},
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

    required = frozenset(Capability(c) for c in (req.required_capabilities or []))
    try:
        # Conversion must stay after validation: an unknown id would otherwise raise
        # ValueError here and surface as a 500 instead of a 422.
        r = mgr.create(duration, required_capabilities=required, device_id=req.interface)
    except UnknownDeviceError:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown interface '{req.interface}'",
        )
    except CapabilityUnsatisfiableError as exc:
        # 422, not 409: no amount of waiting adds capabilities to the pool, so the
        # client must change the request. The frontend keys its retry countdown off
        # 409 and must not start one here.
        if exc.device_id is not None:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Device does not provide the requested capabilities",
                    "interface": exc.device_id,
                    "missing": sorted(c.value for c in exc.missing),
                },
            )
        raise HTTPException(
            status_code=422,
            detail={
                "error": "No device provides the requested capabilities",
                "requested": sorted(c.value for c in required),
                "available_capabilities": exc.available,
            },
        )
    except NoDeviceAvailableError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "No device available",
                "requested_capabilities": sorted(c.value for c in required),
                # Both null when every matching device is held by an unlimited
                # reservation: there is no scheduled release to report.
                # tz=timezone.utc to match _build_response(): without it this field was
                # rendered in the host's local time while every other timestamp in the
                # API was UTC, so the two disagreed by the machine's offset.
                "next_available_at": (
                    datetime.fromtimestamp(
                        exc.next_available_at, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    if exc.next_available_at is not None else None
                ),
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
        capabilities=config.capabilities_for(r.device_id),
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
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """Release a reservation and free the device."""
    # Resolve device_id before deletion (delete removes the record)
    reservation = mgr.get(reservation_id)
    removed = mgr.delete(reservation_id)
    if not removed:
        raise HTTPException(
            status_code=404, detail="Reservation not found or already expired"
        )
    # Best-effort: stop any active network on the released device
    if reservation and reservation.device_id in manager.active:
        try:
            manager.stop_network(reservation.device_id)
            logger.info("Network %s stopped on reservation release", reservation.device_id)
        except Exception:
            logger.exception("Failed to stop network %s on reservation release", reservation.device_id)
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
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """Release all active reservations at once."""
    # Collect device_ids before deletion removes the records
    device_ids = [r.device_id for r in mgr.all_active()]
    count = mgr.delete_all()
    # Best-effort: stop any active networks on released devices
    for device_id in device_ids:
        if device_id in manager.active:
            try:
                manager.stop_network(device_id)
                logger.info("Network %s stopped on bulk reservation release", device_id)
            except Exception:
                logger.exception("Failed to stop network %s on bulk reservation release", device_id)
    return {"detail": f"{count} reservation(s) released", "released": count}
