"""QoS (Quality of Service) management endpoints."""

from fastapi import APIRouter, Body, Depends, HTTPException

from ...models import QosRequest, QosStatus
from ...network.qos import QosManager
from ...reservation import Reservation
from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager, get_qos_manager, resolve_reservation

router = APIRouter(prefix="/interface", tags=["QoS"])


def _require_active_network(
    device_id: str, manager: NetworkManager
) -> str:
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


@router.post(
    "/{reservation_id}/qos",
    response_model=QosStatus,
    responses={
        200: {
            "description": "QoS settings applied successfully",
            "content": {
                "application/json": {
                    "example": {
                        "interface": "wlan0",
                        "active": True,
                        "download_speed_kbit": 8000,
                        "upload_speed_kbit": 3000,
                        "download_quality": 80,
                        "upload_quality": 65,
                        "download_netem_params": {
                            "packet_loss_percent": 1.2,
                            "delay_ms": 40,
                            "jitter_ms": 12,
                            "corruption_percent": 0.008,
                            "delay_distribution": "normal",
                        },
                        "upload_netem_params": {
                            "packet_loss_percent": 3.68,
                            "delay_ms": 122,
                            "jitter_ms": 37,
                            "corruption_percent": 0.043,
                            "delay_distribution": "normal",
                        },
                    }
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
        409: {"description": "Network not active on this reservation"},
        422: {"description": "Invalid speed range or request format"},
    },
    summary="Apply or update QoS settings",
    description=(
        "Apply or update bandwidth throttling and/or link quality degradation.\n\n"
        "**Partial update semantics:**\n"
        "- Omitted field → keep current value\n"
        "- Field set to a value → apply/update\n"
        "- Field set to `null` → reset to unlimited/inactive\n\n"
        "At least one field must be present in the request body.\n\n"
        "**Speed fields:** `download_speed_kbit`, `upload_speed_kbit` (1–1000000 kbit/s)\n\n"
        "**Quality fields:** `download_quality`, `upload_quality` (0–100%, 100 = perfect)\n\n"
        "The quality score is mapped to netem impairments via quadratic/cubic curves:\n\n"
        "| Quality | Packet Loss | Delay | Jitter | Corruption | Perceived |\n"
        "|---------|-------------|-------|--------|------------|-----------|\n"
        "| 100 | 0% | 0 ms | 0 ms | 0% | Perfect |\n"
        "| 90 | 0.3% | 10 ms | 3 ms | ~0% | Near-perfect |\n"
        "| 75 | 1.9% | 62 ms | 19 ms | 0.002% | Slightly degraded |\n"
        "| 50 | 7.5% | 250 ms | 75 ms | 0.125% | Noticeable |\n"
        "| 25 | 16.9% | 562 ms | 169 ms | 0.42% | Poor |\n"
        "| 0 | 30% | 1000 ms | 300 ms | 1% | Nearly unusable |\n\n"
        "**Advanced override:** `download_quality_advanced`, `upload_quality_advanced` — "
        "when provided, **replaces** the formula entirely with your exact netem values. "
        "Fields:\n\n"
        "| Field | Type | Range | Default |\n"
        "|-------|------|-------|---------|\n"
        "| `packet_loss_percent` | float | 0–100 | 0 |\n"
        "| `delay_ms` | int | 0–5000 | 0 |\n"
        "| `jitter_ms` | int | 0–1000 | 0 |\n"
        "| `corruption_percent` | float | 0–5 | 0 |\n"
        "| `delay_distribution` | string | normal / pareto / paretonormal | normal |\n\n"
        "**Advanced override example:**\n"
        "```json\n"
        '{\n'
        '  "download_quality": 90,\n'
        '  "upload_quality_advanced": {\n'
        '    "packet_loss_percent": 5.5,\n'
        '    "delay_ms": 140,\n'
        '    "jitter_ms": 25,\n'
        '    "corruption_percent": 0.2,\n'
        '    "delay_distribution": "paretonormal"\n'
        '  }\n'
        '}\n'
        "```\n"
        "In this example download uses the formula (quality=90), while upload uses "
        "the exact values specified in the advanced object."
    ),
)
async def apply_qos(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
    qos: QosManager = Depends(get_qos_manager),
    body: dict = Body(...),
):
    """Apply or update QoS settings on the reserved interface."""
    device_id = reservation.device_id
    interface = _require_active_network(device_id, manager)

    # Parse and validate through Pydantic (only known fields)
    try:
        req = QosRequest(**{k: v for k, v in body.items() if k in QosRequest.model_fields})
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Must provide at least one field
    provided = {k for k in QosRequest.model_fields if k in body}
    if not provided:
        raise HTTPException(status_code=422, detail="At least one QoS field must be provided")

    # Build kwargs with sentinel for omitted fields
    kwargs: dict = {}
    for field_name in (
        "download_speed_kbit", "upload_speed_kbit",
        "download_quality", "upload_quality",
        "download_quality_advanced", "upload_quality_advanced",
    ):
        if field_name in body:
            kwargs[field_name] = getattr(req, field_name)
        # else: omitted → _SENTINEL (default in apply_qos)

    try:
        qos.apply_qos(interface, **kwargs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to apply QoS: {e}")

    return _build_status(interface, qos)


@router.get(
    "/{reservation_id}/qos",
    response_model=QosStatus,
    responses={
        200: {
            "description": "Current QoS status",
            "content": {
                "application/json": {
                    "example": {
                        "interface": "wlan0",
                        "active": True,
                        "download_speed_kbit": 8000,
                        "upload_speed_kbit": 3000,
                        "download_quality": 80,
                        "upload_quality": None,
                        "download_netem_params": {
                            "packet_loss_percent": 1.2,
                            "delay_ms": 40,
                            "jitter_ms": 12,
                            "corruption_percent": 0.008,
                            "delay_distribution": "normal",
                        },
                        "upload_netem_params": None,
                    }
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
    },
    summary="Get current QoS status",
    description="Retrieve the current QoS settings for the reserved interface.",
)
async def get_qos(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
    qos: QosManager = Depends(get_qos_manager),
):
    """Return current QoS status for the reserved interface."""
    device_id = reservation.device_id
    st = manager.get_status(device_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown device_id")
    return _build_status(st.interface, qos)


@router.delete(
    "/{reservation_id}/qos",
    responses={
        200: {
            "description": "All QoS rules cleared",
            "content": {
                "application/json": {
                    "example": {"detail": "QoS cleared successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
    },
    summary="Clear all QoS rules",
    description="Remove all QoS rules (speed throttling and link quality) from the reserved interface.",
)
async def clear_qos(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
    qos: QosManager = Depends(get_qos_manager),
):
    """Clear all QoS rules from the reserved interface."""
    device_id = reservation.device_id
    st = manager.get_status(device_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown device_id")

    try:
        qos.clear_qos(st.interface)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear QoS: {e}")

    return {"detail": "QoS cleared successfully"}


def _build_status(interface: str, qos: QosManager) -> QosStatus:
    state = qos.get_status(interface)
    if state is None:
        return QosStatus(interface=interface, active=False)
    return QosStatus(
        interface=interface,
        active=state.active,
        download_speed_kbit=state.download_speed_kbit,
        upload_speed_kbit=state.upload_speed_kbit,
        download_quality=state.download_quality,
        upload_quality=state.upload_quality,
        download_netem_params=state.download_netem_params,
        upload_netem_params=state.upload_netem_params,
    )
