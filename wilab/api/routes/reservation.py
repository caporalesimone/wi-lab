"""Device reservation endpoints (create, query, release)."""

import logging
from datetime import datetime, timezone

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...api.auth import require_token
from ...api.dependencies import get_config, get_manager, get_reservation_manager
from ...config import AppConfig, Capability, normalise_capability_id
from ...reservation import (
    CapabilityUnsatisfiableError,
    NoDeviceAvailableError,
    ReservationManager,
)
from ...wifi.manager import NetworkManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/device-reservation", tags=["Reservation"])


# ---- Request / Response models ----

class ReservationCreateRequest(BaseModel):
    # Unknown fields are rejected, not ignored: a client that still sends the removed
    # `interface` must be told, not left believing it pinned a device.
    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(
        ..., description="Reservation duration in seconds (0 = unlimited, if allowed by config)",
        json_schema_extra={"example": 3600}
    )
    required_capabilities: List[str] = Field(
        ...,
        description=(
            "Capabilities the assigned device must provide. REQUIRED: a client must state "
            "what it needs. An empty list explicitly means \"any device\". Wi-Lab assigns "
            "the least capable matching free device, so scarce multi-band hardware stays "
            "available for requests that need it."
        ),
        json_schema_extra={"example": ["2.4ghz"]},
    )

    @field_validator("duration_seconds")
    @classmethod
    def validate_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(
                "duration_seconds must not be negative (use 0 for unlimited)"
            )
        return v

    @field_validator("required_capabilities")
    @classmethod
    def validate_capability_ids(cls, v: List[str]) -> List[str]:
        """Canonicalise and validate ids against the same registry the config uses.

        Normalisation goes through the shared normalise_capability_id(), so the file and
        the wire cannot drift on "5GHz". The result is de-duplicated and sorted, which
        makes the endpoint independent of client-side ordering.
        """
        canonical = [normalise_capability_id(c) for c in v]
        unknown = sorted({c for c in canonical if c not in Capability.ids()})
        if unknown:
            raise ValueError(
                f"Unknown capabilities: {', '.join(unknown)}. "
                f"Valid: {', '.join(Capability.ids())}"
            )
        return sorted(set(canonical))


class ReservationResponse(BaseModel):
    reservation_id: str = Field(
        ...,
        description="Token identifying the reservation. Use it as `{reservation_id}` in "
                    "every other endpoint and to release the device.",
        json_schema_extra={"example": "a1b2c3d4"},
    )
    display_name: str = Field(
        ..., description="Human-readable name of the assigned device, from config.yaml.",
        json_schema_extra={"example": "bench-antenna-1"},
    )
    interface: str = Field(
        ..., description="Network interface Wi-Lab assigned to you. You cannot choose it.",
        json_schema_extra={"example": "wlxbc071dc527d6"},
    )
    expires_at: Optional[str] = Field(
        None,
        description="Expiration datetime in UTC (yyyy-mm-dd HH:MM:SS), null if unlimited",
        json_schema_extra={"example": "2026-10-05 15:15:00"},
    )
    expires_in: Optional[int] = Field(
        None, description="Seconds remaining until expiry, null if unlimited",
        json_schema_extra={"example": 900},
    )
    capabilities: List[str] = Field(
        ...,
        description="Capabilities the assigned device provides (enabled ones only, sorted). "
                    "Lets a client know what it actually got without cross-referencing /status.",
        json_schema_extra={"example": ["2.4ghz"]},
    )


def _display_name_for(device_id: str, config: AppConfig) -> str:
    """Look up user-facing display name from config."""
    for n in config.networks:
        if n.device_id == device_id:
            return n.display_name
    return device_id


# ---- Endpoints ----

_RESERVATION_REQUEST_EXAMPLES: Dict[str, Any] = {
    "any_device": {
        "summary": "Any device",
        "description": "No requirement: `required_capabilities` is mandatory but may be empty. "
                       "Wi-Lab assigns the least capable free device.",
        "value": {"duration_seconds": 900, "required_capabilities": []},
    },
    "needs_5ghz": {
        "summary": "I need 5 GHz",
        "description": "Only a device with 5 GHz enabled can be assigned.",
        "value": {"duration_seconds": 3600, "required_capabilities": ["5ghz"]},
    },
    "dual_band": {
        "summary": "I need both bands",
        "description": "The device must provide every listed capability.",
        "value": {"duration_seconds": 3600, "required_capabilities": ["2.4ghz", "5ghz"]},
    },
    "unlimited": {
        "summary": "Unlimited reservation",
        "description": "`duration_seconds: 0`, accepted only when `allow_unlimited_reservation` "
                       "is true in config.yaml. Must be released manually.",
        "value": {"duration_seconds": 0, "required_capabilities": ["2.4ghz"]},
    },
}

_RESERVATION_CREATE_RESPONSES: dict = {
    200: {
        "description": "Device reserved successfully",
        "content": {"application/json": {"example": {
            "reservation_id": "a1b2c3d4",
            "display_name": "bench-antenna-1",
            "interface": "wlxbc071dc527d6",
            "expires_at": "2026-10-05 15:15:00",
            "expires_in": 900,
            "capabilities": ["2.4ghz"],
        }}},
    },
    401: {
        "description": "Unauthorized",
        "content": {"application/json": {"example": {"detail": "Invalid token"}}},
    },
    409: {
        "description": "Devices providing the requested capabilities exist but are all "
                       "reserved. **Transient**: retry after `next_available_in` seconds. "
                       "Both `next_available_*` are `null` when every matching device is held "
                       "by an unlimited reservation: there is no scheduled release, so do not "
                       "start a countdown. `next_available_at` is UTC.",
        "content": {"application/json": {"examples": {
            "release_scheduled": {
                "summary": "A matching device frees up at a known time",
                "value": {"detail": {
                    "error": "No device available",
                    "requested_capabilities": ["5ghz"],
                    "next_available_at": "2026-10-05 14:20:00",
                    "next_available_in": 312,
                }},
            },
            "unlimited_holders": {
                "summary": "Every matching device is held without expiry",
                "value": {"detail": {
                    "error": "No device available",
                    "requested_capabilities": ["5ghz"],
                    "next_available_at": None,
                    "next_available_in": None,
                }},
            },
        }}},
    },
    422: {
        "description": "The request is invalid. **Permanent**: change the request, retrying it "
                       "unchanged will never work. `detail` is a string for missing/invalid "
                       "fields and duration errors, an object when no device can ever provide "
                       "the requested capabilities.",
        "content": {"application/json": {"examples": {
            "missing_field": {
                "summary": "Mandatory field missing (every 3.x client)",
                "value": {"detail": "Missing required field(s): required_capabilities"},
            },
            "unknown_field": {
                "summary": "Unknown field, e.g. the removed `interface`",
                "value": {"detail": "interface: Extra inputs are not permitted"},
            },
            "unknown_capability": {
                "summary": "Capability id that does not exist",
                "value": {"detail": "required_capabilities: Value error, Unknown capabilities: "
                                    "6ghz. Valid: 2.4ghz, 5ghz"},
            },
            "unsatisfiable": {
                "summary": "No configured device provides the capabilities",
                "value": {"detail": {
                    "error": "No device provides the requested capabilities",
                    "requested": ["5ghz"],
                    "available_capabilities": ["2.4ghz"],
                }},
            },
            "duration_out_of_range": {
                "summary": "duration_seconds outside min_timeout/max_timeout",
                "value": {"detail": "duration_seconds must be at least 60 seconds"},
            },
        }}},
    },
}


@router.post(
    "",
    response_model=ReservationResponse,
    summary="Reserve a device",
    responses=_RESERVATION_CREATE_RESPONSES,
)
async def create_reservation(
    req: ReservationCreateRequest = Body(..., openapi_examples=_RESERVATION_REQUEST_EXAMPLES),
    config: AppConfig = Depends(get_config),
    mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
):
    """Reserve a device for a given time.

    You state **what you need** (`required_capabilities`); Wi-Lab always chooses the
    device. It assigns the **least capable free device** that provides every requested
    capability (ties go to the first in `config.yaml`), so multi-band adapters stay free for
    requests that really need them. You cannot ask for a specific antenna.

    Both `duration_seconds` and `required_capabilities` are **mandatory** (`[]` means "any
    device"); a request missing either is rejected with 422 listing every missing field.
    Unknown fields are rejected too.

    Read `interface` and `capabilities` from the response to know what you got, then use
    `reservation_id` with the other endpoints. Creating a network on a band the device does
    not provide is not prevented by this endpoint: check `capabilities` first.

    - **409** means *wait* (matching devices busy); **422** means *change the request*.
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

    required = frozenset(Capability(c) for c in req.required_capabilities)
    try:
        # Conversion must stay after validation: an unknown id would otherwise raise
        # ValueError here and surface as a 500 instead of a 422.
        r = mgr.create(duration, required_capabilities=required)
    except CapabilityUnsatisfiableError as exc:
        # 422, not 409: no amount of waiting adds capabilities to the pool, so the
        # client must change the request. The frontend keys its retry countdown off
        # 409 and must not start one here.
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
    summary="Get a reservation",
    responses={
        200: {"description": "Reservation details, including the capabilities of the assigned device"},
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
    summary="Release a reservation",
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
    summary="Release all reservations",
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
