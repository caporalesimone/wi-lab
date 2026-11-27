from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request

from ..config import AppConfig
from ..devices import DeviceRegistry
from ..network.qos import QosManager
from ..network.qos_profile import QosProfileManager
from ..reservation import Reservation, ReservationManager
from ..wifi.channels import ChannelManager
from ..wifi.manager import NetworkManager
from .context import AppContext
from .errors import GONE_REASONS

# Request dependencies: each reads the AppContext the app was built with (ARCH-5).


def get_context(request: Request) -> AppContext:
    context: AppContext = request.app.state.context
    return context


def get_config(request: Request) -> AppConfig:
    return get_context(request).config


def get_devices(request: Request) -> DeviceRegistry:
    return get_context(request).devices


def get_manager(request: Request) -> NetworkManager:
    return get_context(request).manager


def get_reservation_manager(request: Request) -> ReservationManager:
    return get_context(request).reservations


def get_channel_manager(request: Request) -> ChannelManager:
    return get_context(request).channels


def get_qos_manager(request: Request) -> QosManager:
    return get_context(request).qos


def get_qos_profile_manager(request: Request) -> QosProfileManager:
    return get_context(request).qos_profiles


ReservationManagerDep = Annotated[ReservationManager, Depends(get_reservation_manager)]
DevicesDep = Annotated[DeviceRegistry, Depends(get_devices)]


def reservation_gone(mgr: ReservationManager, reservation_id: str) -> HTTPException:
    """404 whose stable `reason` says why the ID is no longer valid (contract)."""
    reason = mgr.ended_reason(reservation_id)
    return HTTPException(status_code=404, detail={
        "code": 404, "reason": reason, "message": f"Reservation {GONE_REASONS[reason]}",
    })


def resolve_reservation(
    reservation_id: str = Path(..., description="Reservation token"),
    mgr: ReservationManager = Depends(get_reservation_manager),
) -> Reservation:
    """Validate reservation_id and return the active Reservation.

    Raises 404 if the token is unknown, expired, or already released.
    """
    r = mgr.get(reservation_id)
    if r is None:
        raise reservation_gone(mgr, reservation_id)
    return r


# Longest wait for another operation on the same device before answering
# 503 / 1006 device_busy (RACE-1). A start round holds the device up to about 40 s, several minutes on DFS.
DEVICE_BUSY_TIMEOUT = 5.0


@contextmanager
def hold_reservation(
    mgr: ReservationManager, reservation: Reservation, *, wait: bool = False,
) -> Iterator[None]:
    """Hold the reservation's device.

    Raises `DeviceBusyError` after `DEVICE_BUSY_TIMEOUT` seconds, or waits until
    the device is free with `wait=True`.
    """
    timeout = None if wait else DEVICE_BUSY_TIMEOUT
    with mgr.hold(reservation.reservation_id, timeout=timeout) as current:
        if current is not reservation:
            raise reservation_gone(mgr, reservation.reservation_id)
        yield
