"""QoS Profile endpoints — catalogue browsing and per-reservation profile control."""

import time

from fastapi import APIRouter, Depends, HTTPException

from ...api.auth import require_token
from ...api.dependencies import (
    ReservationManagerDep,
    get_manager,
    get_qos_manager,
    get_qos_profile_manager,
    hold_reservation,
    resolve_reservation,
)
from ...api.errors import ApiErrorCode, domain_error
from ...models import (
    QosProfile,
    QosProfileStartRequest,
    QosProfileState,
    QosProfileStepState,
)
from ...network.qos import QosManager
from ...network.qos_profile import QosProfileManager
from ...reservation import Reservation
from ...wifi.manager import NetworkManager, NetworkNotActive
from .recovery_responses import (
    DEVICE_BUSY_RESPONSE,
    NETWORK_NOT_ACTIVE_EXAMPLE,
    NETWORK_NOT_ACTIVE_RESPONSE,
    STOP_INCOMPLETE_EXAMPLE,
    require_stop_complete,
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


# ---------------------------------------------------------------------------
# Reservation router — requires auth + active network
# ---------------------------------------------------------------------------

reservation_router = APIRouter(
    prefix="/reservations", tags=["QoS Profiles"],
    responses={503: {"description": "Adapter busy (1006): repeat after Retry-After"}},
)


def _require_active_network(device_id: str, manager: NetworkManager) -> str:
    """Return the physical interface name, or raise NetworkNotActive (409 / 1007, API-2).

    A half-stopped network is 409 / 1012 (REV-9).
    """
    require_stop_complete(manager, device_id)
    st = manager.get_status(device_id)
    if st is None or not st.active:
        raise NetworkNotActive(device_id)
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
        source_file=ap.source_file,
        mode=ap.mode,
        steps=len(ap.steps),
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
        503: DEVICE_BUSY_RESPONSE,
        200: {"description": "Profile started successfully"},
        401: {"description": "Unauthorized"},
        404: {"description": "Reservation or profile not found"},
        409: {
            "description": (
                "A profile is already active (stop it first), or `detail.code: 1007` "
                "(`network_not_active`): the reservation has no running network, or "
                "`detail.code: 1012` (`stop_incomplete`): the network is half stopped, "
                "repeat `DELETE .../network`."
            ),
            "content": {"application/json": {"examples": {
                "network_not_active": {"value": NETWORK_NOT_ACTIVE_EXAMPLE},
                "stop_incomplete": {"value": STOP_INCOMPLETE_EXAMPLE},
            }}},
        },
        422: {"description": "Invalid request body"},
    },
    summary="Start a QoS profile on the reservation",
    description=(
        "Start a QoS profile from the catalogue **or** provide inline QoS parameters.\n\n"
        "**Option 1 — catalogue profile:**\n"
        '```json\n{ "profile_id": "4g_urban_moving" }\n```\n\n'
        "**Option 2 — inline QoS (auto-generates a `once-hold-last` profile):**\n"
        '```json\n{ "download_speed_kbit": 1000, "download_quality": 40 }\n```\n\n'
        "Only one format is allowed per request. Providing both or neither returns 422.\n\n"
        "If a profile is already active on the interface, returns 409. Stop it first."
    ),
)
def start_profile(
    body: QosProfileStartRequest,
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
    qos: QosManager = Depends(get_qos_manager),
    pm: QosProfileManager = Depends(get_qos_profile_manager),
):
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        interface = _require_active_network(device_id, manager)

        if pm.is_active(interface):
            raise HTTPException(status_code=409, detail=domain_error(
                ApiErrorCode.QOS_PROFILE_ALREADY_ACTIVE,
                "A profile is already active on this interface. Stop it first.",
            ))

        if body.profile_id is not None:
            profile = pm.get_profile(body.profile_id)
            if profile is None:
                # A body error, not a missing reservation: 404 always means the ID is gone.
                raise HTTPException(
                    status_code=422, detail=f"profile_id: profile '{body.profile_id}' not found in catalogue",
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
        503: DEVICE_BUSY_RESPONSE,
        200: {"description": "Current profile state"},
        401: {"description": "Unauthorized"},
        404: {"description": "Reservation not found"},
        409: NETWORK_NOT_ACTIVE_RESPONSE,
    },
    summary="Get active QoS profile state",
    description="Returns the current profile state for the reserved interface, including step progress.",
)
def get_profile_state(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
    pm: QosProfileManager = Depends(get_qos_profile_manager),
):
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        return _build_profile_state(_require_active_network(device_id, manager), pm)


@reservation_router.delete(
    "/{reservation_id}/qos/profile",
    status_code=200,
    responses={
        503: DEVICE_BUSY_RESPONSE,
        200: {"description": "Profile stopped and QoS cleared"},
        401: {"description": "Unauthorized"},
        404: {"description": "Reservation not found / no active profile"},
        409: NETWORK_NOT_ACTIVE_RESPONSE,
    },
    summary="Stop the active QoS profile",
    description="Stops the active profile and clears all QoS rules from the interface.",
)
def stop_profile(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
    qos: QosManager = Depends(get_qos_manager),
    pm: QosProfileManager = Depends(get_qos_profile_manager),
):
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        interface = _require_active_network(device_id, manager)

        ap = pm.get_state(interface)
        if ap is None or not ap.active:
            raise HTTPException(status_code=409, detail=domain_error(
                ApiErrorCode.QOS_PROFILE_NOT_ACTIVE, "No active profile on this interface",
            ))

        profile_id = ap.profile_id
        pm.stop_profile(interface, qos)
        ap_after = pm.get_state(interface)
        if ap_after is not None and ap_after.active:
            raise HTTPException(status_code=500, detail=f"Failed to deactivate profile '{profile_id}'")

        return {"detail": f"Profile '{profile_id}' deactivated correctly."}
