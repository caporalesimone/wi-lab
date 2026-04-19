"""QoS Profile endpoints — catalogue browsing and per-reservation profile control."""

import time

from fastapi import APIRouter, Depends, HTTPException

from ...models import (
    QosProfile,
    QosProfileStartRequest,
    QosProfileState,
    QosProfileStepState,
)
from ...network.qos import QosManager
from ...network.qos_profile import QosProfileManager
from ...reservation import Reservation
from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import (
    get_manager,
    get_qos_manager,
    get_qos_profile_manager,
    resolve_reservation,
)

# ---------------------------------------------------------------------------
# Catalogue router — global, no auth
# ---------------------------------------------------------------------------

catalogue_router = APIRouter(prefix="/qos", tags=["QoS Profiles"])


@catalogue_router.get(
    "/profiles",
    response_model=list[QosProfile],
    summary="List all available QoS profiles",
    description="Returns the full catalogue of QoS profiles shipped with wi-lab and any user-added profiles.",
)
async def list_profiles(
    pm: QosProfileManager = Depends(get_qos_profile_manager),
):
    return pm.list_profiles()


@catalogue_router.get(
    "/profiles/{profile_id}",
    response_model=QosProfile,
    responses={404: {"description": "Profile not found in catalogue"}},
    summary="Get a single QoS profile by ID",
    description="Returns the full detail of a profile including all steps.",
)
async def get_profile(
    profile_id: str,
    pm: QosProfileManager = Depends(get_qos_profile_manager),
):
    profile = pm.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return profile


# ---------------------------------------------------------------------------
# Reservation router — requires auth + active network
# ---------------------------------------------------------------------------

reservation_router = APIRouter(prefix="/interface", tags=["QoS Profiles"])


def _require_active_network(device_id: str, manager: NetworkManager) -> str:
    """Return the physical interface name or raise 409."""
    st = manager.get_status(device_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown device_id")
    if not st.active:
        raise HTTPException(
            status_code=409,
            detail="Cannot apply QoS: network is not active for this reservation",
        )
    return st.interface


def _build_profile_state(interface: str, pm: QosProfileManager) -> QosProfileState:
    """Build the current profile state response for an interface."""
    ap = pm.get_state(interface)
    if ap is None or not ap.active:
        return QosProfileState(interface=interface, active=False)

    now = time.monotonic()
    step = ap.steps[ap.step_index]
    elapsed_step = int(now - ap.step_started_at)
    total_elapsed = int(now - ap.started_at)

    return QosProfileState(
        interface=interface,
        active=True,
        profile_id=ap.profile_id,
        description=ap.description,
        mode=ap.mode,
        current_step=QosProfileStepState(
            index=ap.step_index,
            elapsed_sec=elapsed_step,
            duration_sec=step.duration_sec,
        ),
        total_elapsed_sec=total_elapsed,
    )


@reservation_router.post(
    "/{reservation_id}/qos/profile",
    response_model=QosProfileState,
    responses={
        200: {"description": "Profile started successfully"},
        401: {"description": "Unauthorized"},
        404: {"description": "Reservation or profile not found"},
        409: {"description": "A profile is already active or network not active"},
        422: {"description": "Invalid request body"},
    },
    summary="Start a QoS profile on the reservation",
    description=(
        "Start a QoS profile from the catalogue **or** provide inline QoS parameters.\n\n"
        "**Option 1 — catalogue profile:**\n"
        '```json\n{ "profile_id": "4g_urban_moving" }\n```\n\n'
        "**Option 2 — inline QoS (auto-generates a `hold` profile):**\n"
        '```json\n{ "download_speed_kbit": 1000, "download_quality": 40 }\n```\n\n'
        "Only one format is allowed per request. Providing both or neither returns 422.\n\n"
        "If a profile is already active on the interface, returns 409. Stop it first."
    ),
)
async def start_profile(
    body: QosProfileStartRequest,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
    qos: QosManager = Depends(get_qos_manager),
    pm: QosProfileManager = Depends(get_qos_profile_manager),
):
    device_id = reservation.device_id
    interface = _require_active_network(device_id, manager)

    # Check for already-active profile
    if pm.is_active(interface):
        raise HTTPException(
            status_code=409,
            detail="A profile is already active on this interface. Stop it first.",
        )

    # Resolve profile
    if body.profile_id is not None:
        profile = pm.get_profile(body.profile_id)
        if profile is None:
            raise HTTPException(
                status_code=404, detail=f"Profile '{body.profile_id}' not found in catalogue"
            )
    else:
        profile = QosProfileManager.build_inline_profile(
            download_speed_kbit=body.download_speed_kbit,
            upload_speed_kbit=body.upload_speed_kbit,
            download_quality=body.download_quality,
            upload_quality=body.upload_quality,
            advanced=body.advanced,
        )

    pm.start_profile(interface, profile, qos)

    return _build_profile_state(interface, pm)


@reservation_router.get(
    "/{reservation_id}/qos/profile",
    response_model=QosProfileState,
    responses={
        200: {"description": "Current profile state"},
        401: {"description": "Unauthorized"},
        404: {"description": "Reservation not found"},
    },
    summary="Get active QoS profile state",
    description="Returns the current profile state for the reserved interface, including step progress.",
)
async def get_profile_state(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
    pm: QosProfileManager = Depends(get_qos_profile_manager),
):
    device_id = reservation.device_id
    st = manager.get_status(device_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown device_id")
    return _build_profile_state(st.interface, pm)


@reservation_router.delete(
    "/{reservation_id}/qos/profile",
    status_code=204,
    responses={
        204: {"description": "Profile stopped and QoS cleared"},
        401: {"description": "Unauthorized"},
        404: {"description": "Reservation not found"},
    },
    summary="Stop the active QoS profile",
    description="Stops the active profile and clears all QoS rules from the interface. No-op if no profile is active.",
)
async def stop_profile(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
    qos: QosManager = Depends(get_qos_manager),
    pm: QosProfileManager = Depends(get_qos_profile_manager),
):
    device_id = reservation.device_id
    st = manager.get_status(device_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown device_id")
    pm.stop_profile(st.interface, qos)
