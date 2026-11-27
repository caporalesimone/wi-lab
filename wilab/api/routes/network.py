"""WiFi network lifecycle endpoints (create, delete, query)."""

import logging
import threading
from time import monotonic, sleep, time
from typing import Literal, NamedTuple

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from ... import log
from ...api.auth import require_token
from ...api.dependencies import (
    ReservationManagerDep,
    get_channel_manager,
    get_manager,
    hold_reservation,
    resolve_reservation,
)
from ...api.errors import (
    DEVICE_BUSY_RETRY_AFTER,
    ApiErrorCode,
    domain_error,
    error_detail,
)
from ...models import (
    NetworkCreateBody,
    NetworkCreateRequest,
    NetworkResponse,
    ReservationInfo,
    RestartsInfo,
    StartError,
    body_error,
)
from ...network.commands import CommandError
from ...reservation import EXPIRED, Reservation, ReservationManager
from ...timestamps import format_utc_timestamp
from ...wifi.channels import ChannelManager, FieldError
from ...wifi.failures import FailureKind
from ...wifi.hostapd import AP_READY_TIMEOUT, DFS_READY_TIMEOUT
from ...wifi.manager import (
    UNKNOWN_ANTENNA,
    NetworkManager,
    NetworkStopError,
    StartJob,
    StartupFailure,
)
from .recovery_responses import (
    DEVICE_BUSY_RESPONSE,
    device_busy_detail,
)

# After a radio failure the create job starts the AP again after these pauses.
CREATE_RETRY_DELAYS = (5, 10)

# What the create job does with a failed start, by kind (ARCH-2). A cancelled
# start (release or stop meanwhile) ends as cancelled whatever the kind, except
# "refuse", where nothing was started:
# - refuse: start_failed (1013), nothing started, no channel re-read
# - fail: rolled back, reservation kept, start_failed (1013) with the stage
# - retry: start again after CREATE_RETRY_DELAYS, then quarantine (radio fault),
#   or end the reservation if it expires too soon for another start
# - quarantine: never retried, the rollback left resources up: isolate the
#   adapter (USB recovery only when kind.radio)
_ON_START_FAILURE: dict[FailureKind, Literal["refuse", "fail", "retry", "quarantine"]] = {
    FailureKind.CONFLICT: "refuse",
    FailureKind.CONFIGURATION: "fail",
    FailureKind.TRANSIENT_RADIO: "retry",
    FailureKind.CLEANUP_FAILED: "quarantine",
    FailureKind.RADIO_CLEANUP_FAILED: "quarantine",
}
START_MARGIN = 5.0   # seconds for gateway, DHCP, NAT and the rest after the AP is up

# Seconds before repeating a stop that did not complete (hostapd stuck in the
# kernel usually exits within a few seconds).
STOP_RETRY_AFTER = 5
# A stop that did not complete is repeated inside the request: hostapd stuck in
# the kernel after a driver firmware timeout is usually released within seconds.
STOP_RETRY_BUDGET = 15.0
STOP_RETRY_PAUSE = 2.0

_STOP_RESPONSE_503 = {
    **DEVICE_BUSY_RESPONSE,
    "description": (
        "`detail.code: 1006` (`device_busy`): the adapter is busy, nothing was changed; repeat "
        "after `Retry-After` (2 s). `detail.code: 1012` (`stop_incomplete`): the stop did not "
        "complete even after the server repeated it for 15 s (hostapd stuck in the kernel after "
        "a driver firmware timeout). The network is half stopped: `GET .../network` reports "
        "`runtime_state: stop_failed` and the watchdog leaves it alone. Repeat the DELETE after "
        "`Retry-After` (5 s)."
    ),
    "content": {"application/json": {"examples": {
        **DEVICE_BUSY_RESPONSE["content"]["application/json"]["examples"],  # type: ignore[index]
        "stop_incomplete": {"summary": "1012 - stop not completed, repeat after Retry-After", "value": {"detail": {
            "code": 1012, "reason": "stop_incomplete",
            "message": "Failed to stop network wlan0: hostapd: Failed to stop hostapd for wlan0: "
                       "Process 101153 stuck in the kernel",
        }}},
    }}},
}

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/reservations", tags=["Network"],
)


_ACTIVE_EXAMPLE = {
    "interface": "wlx7419f8176286", "active": True, "runtime_state": None,
    "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 3471},
    "restarts": {"ap": 0, "dhcp": 0, "last_at": None, "last_reason": None},
    "radio": {
        "band": "5ghz", "channel": 36,
        "channel_width": {"requested": 80, "reported": 80},
        "wifi_generation": 5,
        "tx_power": {"requested_level": 4, "reported_level": 4, "reported_dbm": 20.0},
    },
    "wifi": {
        "ssid": "test-network-ap-01", "hidden": False,
        "security": {"encryption": "wpa2", "password": "12345678"},
    },
    "ip": {
        "subnet": "192.168.120.0/24", "gateway": "192.168.120.1",
        "dhcp_range": {"start": "192.168.120.10", "end": "192.168.120.250"},
        "dns_server": "192.168.10.21",
    },
    "internet": {"enabled": True},
    "captive_portal": {"enabled": False, "url": None},
    "clients": [
        {"mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.120.10"},
        {"mac": "aa:bb:cc:dd:ee:02", "ip": "192.168.120.11"},
    ],
}


_STARTING_EXAMPLE = {
    "interface": "wlx7419f8176286", "active": False, "runtime_state": "starting",
    "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 3599},
    "restarts": {"ap": 0, "dhcp": 0, "last_at": None, "last_reason": None},
}


_CREATE_RESPONSES: dict = {
    503: {
        **DEVICE_BUSY_RESPONSE,
        "description": (
            "`detail.code: 1006` (`device_busy`), only for the same body on a network already "
            "running (the `200` case): reading the network waited 5 s for another operation on "
            "the adapter. Nothing was changed; repeat the same create after `Retry-After` (2 s). "
            "A create that starts a network answers `202` at once and never `1006` (REV-11)."
        ),
    },
    202: {
        "description": (
            "Start accepted: the network with `active: false` and `runtime_state: starting` "
            "(the same schema as `GET .../network`). Poll `GET .../network` every 1-2 s. "
            "Also the answer to the same body while that start is running."
        ),
        "content": {"application/json": {"example": _STARTING_EXAMPLE}},
    },
    200: {
        "description": (
            "The same body on a network that is already running with exactly these settings "
            "(e.g. a create repeated after a lost answer): the network, nothing is restarted."
        ),
        "content": {"application/json": {"example": {**_ACTIVE_EXAMPLE, "clients": []}}},
    },
    401: {"description": "Unauthorized", "content": {"application/json": {
        "example": {"detail": error_detail(401, "Invalid token")},
    }}},
    409: {
        "description": (
            "A network with different settings runs or is starting (1008; the same body "
            "answers 202 or 200), a watchdog repair in progress (1009), or the last stop did "
            "not complete (1012: repeat DELETE .../network, then the create)."
        ),
        "content": {"application/json": {"examples": {
            "active_network": {"value": {"detail": domain_error(
                ApiErrorCode.NETWORK_ALREADY_ACTIVE,
                "Network wlan0 is already active. Stop it first before creating a new one.",
            )}},
            "restoration_in_progress": {
                "value": {"detail": domain_error(ApiErrorCode.RESTORATION_IN_PROGRESS, "Network restoration is in progress")},
            },
            "stop_incomplete": {
                "summary": "1012 - the last stop did not complete: repeat DELETE .../network, then the create",
                "value": {"detail": domain_error(
                    ApiErrorCode.STOP_INCOMPLETE,
                    "The stop of the network on wlan0 did not complete: repeat DELETE .../network first",
                )},
            },
        }}},
    },
    422: {
        "description": (
            "Validation failed: body, unsupported or disabled channel, `encryption: wpa` "
            "(no longer accepted), or an encryption, channel width or Wi-Fi generation the "
            "antenna does not support"
        ),
        "content": {"application/json": {"examples": {
            "wpa_removed": {
                "summary": "encryption wpa is no longer accepted",
                "value": {"detail": error_detail(
                    422,
                    "wifi.security.encryption: 'wpa' is no longer accepted: use "
                    "'wpa2' (what 'wpa' used to create) or 'wpa1' for legacy WPA/TKIP",
                )},
            },
            "wpa1_unsupported": {
                "summary": "wpa1 on an antenna without TKIP",
                "value": {"detail": error_detail(
                    422, "wifi.security.encryption: wpa1 is not supported on this antenna",
                )},
            },
            "width_unavailable": {
                "summary": "Channel cannot be used at the requested width",
                "value": {"detail": error_detail(
                    422,
                    "radio.channel_width: 80 MHz on channel 165 is not available: Channel 169 is disabled on wlan0 "
                    "for band 5ghz (regulatory domain restriction)",
                )},
            },
            "generation_unsupported": {
                "summary": "Wi-Fi generation not supported by the antenna",
                "value": {"detail": error_detail(
                    422,
                    "radio.wifi_generation: wifi_generation 6 is not supported on this antenna for band 5ghz",
                )},
            },
            "field_validation": {
                "summary": "Invalid field: the message starts with its path in the body",
                "value": {"detail": error_detail(
                    422, "radio.channel_width: Input should be 20, 40 or 80",
                )},
            },
            "body_validation": {
                "summary": "Rule between fields: the path is the refused field",
                "value": {"detail": error_detail(
                    422,
                    "radio.channel: Channel 99 is not a valid WiFi channel for band 5ghz",
                )},
            },
            "unsupported_channel": {
                "summary": "Channel not supported by hardware",
                "value": {"detail": error_detail(
                    422, "radio.channel: Channel 173 is not supported on wlan0 for band 5ghz",
                )},
            },
            "disabled_channel": {
                "summary": "Channel disabled by regulatory domain",
                "value": {"detail": error_detail(
                    422,
                    "radio.channel: Channel 14 is disabled on wlan0 for band 2.4ghz (regulatory domain restriction)",
                )},
            },
        }}},
    },
}


_CREATE_BODY_EXAMPLES: dict = {
    "wpa2_network": {
        "summary": "2.4 GHz WPA2 network, every optional field at its default",
        "description": "Required: radio.band, radio.channel, radio.tx_power_level, "
        "wifi.ssid, wifi.security.encryption, and wifi.security.password unless the "
        "encryption is open. Optional, shown with their defaults: radio.channel_width, "
        "radio.wifi_generation, wifi.hidden, internet.enabled (default from the server "
        "configuration), captive_portal.enabled.",
        "value": {
        "radio": {
            "band": "2.4ghz", "channel": 5, "channel_width": 20,
            "wifi_generation": 4, "tx_power_level": 4,
        },
        "wifi": {
            "ssid": "TestNetwork", "hidden": False,
            "security": {"encryption": "wpa2", "password": "testpass123"},
        },
        "internet": {"enabled": True},
        "captive_portal": {"enabled": False},
    },
    },
    "wifi5_80mhz": {
        "summary": "5 GHz Wi-Fi 5 network at 80 MHz",
        "description": "Channels 36-48 as one 80 MHz channel, 802.11ac. Needs an antenna "
        "whose GET /antennas/{interface} lists 80 MHz for wifi_generation 5 on 5ghz.",
        "value": {
        "radio": {
            "band": "5ghz", "channel": 36, "channel_width": 80,
            "wifi_generation": 5, "tx_power_level": 4,
        },
        "wifi": {
            "ssid": "Wifi5Test", "hidden": False,
            "security": {"encryption": "wpa2-wpa3", "password": "testpass123"},
        },
        "internet": {"enabled": True},
        "captive_portal": {"enabled": False},
    },
    },
    "wpa1_legacy": {
        "summary": "Legacy WPA (TKIP) network for old clients",
        "description": "Insecure, 802.11a/g only (20 MHz, at most 54 Mbit/s). Accepted "
        "only on antennas whose GET /antennas/{interface} lists wpa1 in encryptions.",
        "value": {
        "radio": {
            "band": "2.4ghz", "channel": 6, "channel_width": 20,
            "wifi_generation": 4, "tx_power_level": 4,
        },
        "wifi": {
            "ssid": "LegacyWpa", "hidden": False,
            "security": {"encryption": "wpa1", "password": "testpass123"},
        },
        "internet": {"enabled": True},
        "captive_portal": {"enabled": False},
    },
    },
    "captive_portal_network": {
        "summary": "Network behind a simulated captive portal",
        "description": "Clients are redirected to the portal page until they press Sign in. "
        "Only the client that signs in is released; with internet.enabled it then reaches "
        "the Internet.",
        "value": {
        "radio": {
            "band": "2.4ghz", "channel": 6, "channel_width": 20,
            "wifi_generation": 4, "tx_power_level": 4,
        },
        "wifi": {
            "ssid": "CaptiveTest", "hidden": False,
            "security": {"encryption": "wpa2", "password": "testpass123"},
        },
        "internet": {"enabled": True},
        "captive_portal": {"enabled": True},
    },
    },
}


@router.post(
    "/{reservation_id}/network",
    response_model=NetworkResponse,
    status_code=202,
    summary="Create a network on a reserved adapter (asynchronous)",
    responses=_CREATE_RESPONSES,
)
def start_network(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    body: NetworkCreateBody = Body(
        ...,
        openapi_examples=_CREATE_BODY_EXAMPLES,
    ),
    manager: NetworkManager = Depends(get_manager),
    channel_mgr: ChannelManager = Depends(get_channel_manager),
):
    """
    Create and start a WiFi network in AP (access point) mode, **asynchronously**.

    The request is checked at once: `422` (invalid body or a setting the antenna
    does not support), `404` (the reservation ID is gone, see `detail.reason`),
    `409 / 1008` (a network with other settings runs or is starting), `409 / 1012`
    (the last stop did not complete: repeat `DELETE .../network`, then the create),
    `409 / 1009` (the watchdog is repairing the network).
    Otherwise the answer is **`202`** with the network in `runtime_state:
    starting`, and the start runs in the background. **Poll `GET .../network`**
    every 1-2 s until one of these outcomes:

    | `GET .../network` | Meaning | Client action |
    |---|---|---|
    | `active: true`, `runtime_state: null` | The AP is up | Done |
    | `runtime_state: start_failed`, `error` | Non-radio failure (`error.code` 1013 with `error.stage`), rolled back; the reservation is still valid | Show the error; a new create starts again, `DELETE .../network` clears it |
    | `404`, `detail.reason: reservation_invalidated` | Every start failed: the antenna is quarantined | Reserve again; do not release the ID |
    | `404`, `detail.reason: reservation_expired` | The reservation expired, also when it would expire before the next start | Reserve again if needed |

    **Radio failures are retried by the server, never by the client:** after a
    hostapd crash, beacon setup failure, radio or readiness timeout the server
    rolls back and starts again, up to 3 times 1 s apart, then after
    5 s and after 10 s. A normal start takes about 0.5 s; with every retry about
    80 s, several minutes on DFS channels (radar check). Expiry is not extended.

    The same body again is safe: `202` while that start runs, `200` with the
    network once it runs. `DELETE .../network` during the start cancels it (the
    reservation stays); releasing the reservation cancels it too. Other calls on
    the reservation answer `503 / 1006` until the start ends.

    **Body:** settings are grouped in `radio`, `wifi` (with `security`),
    `internet` and `captive_portal`, the same sections as `GET .../network`.
    Only `radio` and `wifi` are required.

    **Captive portal** (optional `captive_portal.enabled`, default `false`; omitted means
    no portal): each client that joins is held behind a simple portal page on the
    gateway (`http://<gateway>:8081/`, the port being `captive_portal_port` in the
    configuration; reported as `captive_portal.url`). Until it
    presses **Sign in**, its DNS queries resolve to the gateway, its HTTP requests
    are redirected to the portal and other forwarded traffic, including HTTPS, is
    rejected. Sign-in releases only that client (MAC and IP); there is no API to
    sign a client in. Afterwards the network's `internet.enabled` setting applies.
    Sign-ins are cleared when the AP stops or is restored by the watchdog. A
    portal startup failure is rolled back like any other startup error
    (`start_failed`, `error.stage: captive_portal`).

    **Encryption, channel width and Wi-Fi generation:** `wifi.security.encryption` is one of
    `open`, `wpa2`, `wpa3`, `wpa2-wpa3` or `wpa1` (legacy WPA/TKIP, only on antennas
    that support it). `wpa` is no longer accepted and returns `422`: use `wpa2`.
    Optional `radio.channel_width` (20, 40, 80 MHz; default 20) and `radio.wifi_generation`
    (4 = 802.11n, 5 = 802.11ac, 6 = 802.11ax; default 4) select the radio mode;
    the defaults keep the previous behaviour. `GET /antennas/{interface}` lists
    what the antenna supports; anything else returns `422`.
    40 MHz on 2.4 GHz may fall back to 20 MHz when neighbouring networks are
    present: `GET .../network` reports the actual `radio.channel_width.reported`.
    """
    req = body.to_request()
    device_id = reservation.device_id
    if manager.watchdog.state(reservation) in ("restoring_ap", "restoring_dhcp", "dhcp_failed"):
        raise HTTPException(status_code=409, detail=domain_error(
            ApiErrorCode.RESTORATION_IN_PROGRESS, "Network restoration is in progress",
        ))
    job = manager.start_job(reservation)
    if job is not None and job.state == "starting":
        if job.request == req:
            # The same create again, e.g. after a lost answer: keep polling the same start.
            return _json(202, _state_response(reservation, "starting"))
        raise HTTPException(status_code=409, detail=domain_error(
            ApiErrorCode.NETWORK_ALREADY_ACTIVE,
            f"A network with other settings is starting on {device_id}",
        ))
    if device_id in manager.active:
        if manager.runs(device_id, req):
            # The same create again, usually after a lost answer: it already succeeded.
            with hold_reservation(reservation_mgr, reservation):
                return _json(200, _network_response(manager, reservation))
        if manager.stop_failed(device_id):
            # Its own code, not 1008: the client must repeat the DELETE, then the create.
            raise HTTPException(status_code=409, detail=domain_error(
                ApiErrorCode.STOP_INCOMPLETE,
                f"The stop of the network on {device_id} did not complete: repeat DELETE .../network first",
            ))
        raise HTTPException(status_code=409, detail=domain_error(
            ApiErrorCode.NETWORK_ALREADY_ACTIVE,
            f"Network {device_id} is already active with other settings. Stop it first.",
        ))
    try:
        channel_mgr.validate_network(
            device_id, req.band, req.channel, req.channel_width, req.wifi_generation,
            req.encryption,
        )
    except FieldError as e:
        raise HTTPException(status_code=422, detail=body_error(e.field, str(e)))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except CommandError as e:
        # The channel list cannot be read (`iw` fails, usually because the antenna
        # just disappeared): not a refusal. The start checks again and treats a
        # missing antenna as a radio fault, retried by the server.
        logger.warning("Cannot check the channel of %s before the start: %s", device_id, e)

    with manager.start_jobs_lock:
        running = manager.start_jobs.get(device_id)
        if running is not None and not running.done.is_set():
            if running.reservation is reservation and running.request == req:
                # The same create sent twice at once: one start, both answers 202.
                return _json(202, _state_response(reservation, "starting"))
            raise HTTPException(status_code=409, detail=domain_error(
                ApiErrorCode.NETWORK_ALREADY_ACTIVE, f"A network is starting on {device_id}",
            ))
        job = StartJob(reservation=reservation, request=req)
        job.thread = threading.Thread(
            target=_run_job, args=(manager, channel_mgr, reservation_mgr, job),
            name=f"create-{device_id}", daemon=True,
        )
        manager.start_jobs[device_id] = job
    job.thread.start()
    return _json(202, _state_response(reservation, "starting"))


class StartOutcome(NamedTuple):
    """How a create job ended; read by `GET .../network`, never answered to a request."""

    state: Literal["started", "cancelled", "ended", "start_failed"]
    error: dict | None = None   # `start_failed`: the error detail (always 1013)
    reason: str = ""            # `ended`: why the reservation ended, for the log


def _failed(message: str, stage: str | None = None) -> StartOutcome:
    return StartOutcome("start_failed", domain_error(ApiErrorCode.STARTUP_FAILED, message, stage=stage))


def _run_start(
    manager: NetworkManager, channel_mgr: ChannelManager, reservation_mgr: ReservationManager,
    reservation: Reservation, req: NetworkCreateRequest, cancel: threading.Event,
) -> StartOutcome:
    """Start the AP, with the server's retries, and say how it ended.

    Holds the device for the whole start. Radio failures are retried here: up to
    3 starts inside `start_network`, then after a 5 s and a 10 s pause. *cancel*
    stops the start at the next check and rolls it back. When every start fails
    the antenna is quarantined (or the reservation expires too soon for another
    start): the reservation ends and `GET` answers 404 with the reason.
    """
    try:
        with hold_reservation(reservation_mgr, reservation, wait=True):
            return _start_with_retries(manager, channel_mgr, reservation_mgr, reservation, req, cancel)
    except HTTPException as exc:   # hold_reservation: the reservation ended while waiting
        return StartOutcome("ended", reason=str(error_detail(exc.status_code, exc.detail).get("reason")))


def _start_with_retries(
    manager: NetworkManager, channel_mgr: ChannelManager, reservation_mgr: ReservationManager,
    reservation: Reservation, req: NetworkCreateRequest, cancel: threading.Event,
) -> StartOutcome:
    device_id = reservation.device_id
    # A new network replaces one the watchdog failed to restore (WD-2).
    manager.watchdog.forget(device_id)
    failures = 0
    while True:
        try:
            manager.start_network(
                device_id, req, expires_at_timestamp=reservation.expires_at,
                allow_internal_retry=failures == 0, cancelled=cancel.is_set,
            )
            return StartOutcome("started")
        except StartupFailure as e:
            action = _ON_START_FAILURE[e.kind]
            if action == "refuse":   # another network is active: nothing was started
                return _failed(str(e), e.stage)
            # The next attempt reads the channel list again (BUG-4).
            channel_mgr.invalidate(device_id)
            if cancel.is_set():
                if e.kind.cleanup_failed:
                    # Not a radio fault and no quarantine (REV-2): what the rollback left
                    # goes to the canceller's path. A release hands it to the background
                    # cleanup, a stop answers 503 / 1012 and its repetition finishes it.
                    logger.warning("AP start on %s cancelled; its rollback failed: %s", device_id, e)
                return StartOutcome("cancelled")
            if action == "fail":
                # Rolled back, reservation kept: the stage tells the client what failed.
                return _failed(str(e), e.stage)
            failures += 1
            if action == "retry" and failures <= len(CREATE_RETRY_DELAYS):
                delay = CREATE_RETRY_DELAYS[failures - 1]
                if _time_left(reservation) >= delay + _start_time(req):
                    logger.info(
                        "AP start on %s failed (%d/%d); starting again in %d s: %s",
                        device_id, failures, len(CREATE_RETRY_DELAYS) + 1, delay, e,
                    )
                    if _pause(cancel, delay):
                        return StartOutcome("cancelled")
                    continue
                # Too little reservation time for another start: free the antenna,
                # the client reserves again (404 reservation_expired).
                logger.warning(
                    "AP start on %s failed and the reservation expires too soon to retry; "
                    "releasing it", device_id,
                )
                reservation_mgr.delete(reservation.reservation_id, EXPIRED)
                return StartOutcome("ended", reason="reservation_expired")
            manager.quarantine_radio(
                reservation_mgr, reservation, radio_fault=e.kind.radio, band=req.band, channel=req.channel,
            )
            return StartOutcome("ended", reason="reservation_invalidated")
        except ValueError as e:   # unknown antenna, no free subnet
            return _failed(str(e))


def _pause(cancel: threading.Event, seconds: float) -> bool:
    """Wait between two starts; True if the start was cancelled meanwhile."""
    return cancel.wait(seconds)


def _run_job(
    manager: NetworkManager, channel_mgr: ChannelManager, reservation_mgr: ReservationManager,
    job: StartJob,
) -> None:
    """Background body of an asynchronous create; the outcome is read with GET .../network."""
    device_id = job.reservation.device_id
    log.bind(antenna=device_id, reservation=job.reservation.reservation_id)   # this thread's whole life
    try:
        try:
            outcome = _run_start(manager, channel_mgr, reservation_mgr, job.reservation, job.request, job.cancel)
        except Exception:  # the outcome must always be readable, never a dead "starting"
            logger.exception("AP start on %s failed unexpectedly", device_id)
            outcome = _failed("Unexpected error during the start")
        if outcome.state == "started":
            logger.info("AP start on %s completed", device_id)
        elif outcome.state == "cancelled":
            logger.info("AP start on %s cancelled and rolled back", device_id)
        elif outcome.state == "ended":
            # GET answers 404 with the reason (invalidated or expired).
            logger.warning("AP start on %s ended its reservation (%s)", device_id, outcome.reason)
        else:
            logger.warning("AP start on %s failed: %s", device_id, (outcome.error or {}).get("message"))
            job.state, job.error = "start_failed", outcome.error
    finally:
        if job.state != "start_failed":   # start_failed stays readable until a new create or a stop
            with manager.start_jobs_lock:
                if manager.start_jobs.get(device_id) is job:
                    del manager.start_jobs[device_id]
        job.done.set()


def _state_response(
    reservation: Reservation, runtime_state: str, error: dict | None = None, *, active: bool = False,
) -> NetworkResponse:
    """A network answered without its sections: starting, start_failed with its error, or restoring."""
    return NetworkResponse(
        interface=reservation.device_id, active=active, runtime_state=runtime_state,
        reservation=ReservationInfo(
            expires_at=format_utc_timestamp(reservation.expires_at),
            expires_in=reservation.expires_in,
        ),
        restarts=_restarts(reservation),
        error=StartError(**error) if error is not None else None,
    )


def _json(status_code: int, response: NetworkResponse) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def _time_left(reservation: Reservation) -> float:
    """Seconds until the reservation expires; infinite when unlimited."""
    if reservation.expires_at is None:
        return float("inf")
    return reservation.expires_at - time()


def _start_time(req) -> float:
    """Longest wait for one AP start on this channel, plus a margin for the rest."""
    dfs = req.band == "5ghz" and 52 <= req.channel <= 144
    return (DFS_READY_TIMEOUT if dfs else AP_READY_TIMEOUT) + START_MARGIN


@router.delete(
    "/{reservation_id}/network",
    responses={
        503: _STOP_RESPONSE_503,
        200: {
            "description": "Network stopped successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network wls16 stopped successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
        409: {"description": "Network already inactive"},
    },
)
def stop_network(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Stop an active WiFi network and clean up all resources.

    Requires a valid reservation token.
    During `runtime_state: starting` this cancels the start and rolls it back;
    with `start_failed` it clears the error. Both return 200 and keep the
    reservation.
    With `runtime_state: restore_failed` (the watchdog could not restart the AP
    and keeps retrying), this stops the retries and returns 200; the
    reservation stays valid.

    If the stop does not complete (usually hostapd stuck in the kernel for a
    few seconds after a driver firmware timeout) the server repeats it every
    2 s for up to 15 s, so the answer can take that long. Only if it still
    fails the answer is `503 / 1012` with `Retry-After`: the network is half
    stopped, reported as `runtime_state: stop_failed`, and repeating the
    DELETE finishes it.
    """
    job = manager.start_job(reservation)
    if job is not None:
        # Cancel a start in progress (it rolls back) or clear a start_failed.
        manager.cancel_start(reservation.device_id)
        if not job.done.is_set():
            raise HTTPException(
                status_code=503, detail=device_busy_detail(),
                headers={"Retry-After": str(DEVICE_BUSY_RETRY_AFTER)},
            )
        if reservation.device_id not in manager.active:
            _release_leftovers(manager, reservation.device_id)
            return {"detail": f"Network {reservation.device_id} stopped successfully"}
        # The start completed just before the cancel: stop the network it left.
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        st = manager.get_status(device_id)
        if not st:
            raise HTTPException(status_code=404, detail=UNKNOWN_ANTENNA)
        if not st.active:
            if manager.has_leftovers(device_id):
                # A start that failed and could not roll back left hostapd or rules (REV-1).
                _release_leftovers(manager, device_id)
                manager.watchdog.forget(device_id)
                return {"detail": f"Network {device_id} stopped successfully"}
            if manager.watchdog.forget(device_id):
                # The client gives up a network the watchdog failed to restore (WD-2).
                return {"detail": f"Network {device_id} stopped successfully"}
            raise HTTPException(status_code=409, detail=domain_error(
                ApiErrorCode.NETWORK_NOT_ACTIVE, f"Network {device_id} is already inactive",
            ))

        deadline = monotonic() + STOP_RETRY_BUDGET
        while True:
            try:
                manager.stop_network(device_id, client=True)
                break
            except NetworkStopError as exc:
                # Usually hostapd stuck in the kernel for a few seconds (driver
                # firmware timeout): repeating the stop finishes it.
                if monotonic() + STOP_RETRY_PAUSE >= deadline:
                    raise HTTPException(
                        status_code=503,
                        detail=domain_error(ApiErrorCode.STOP_INCOMPLETE, str(exc)),
                        headers={"Retry-After": str(STOP_RETRY_AFTER)},
                    ) from exc
                logger.info("Stop of %s did not complete; repeating it: %s", device_id, exc)
                sleep(STOP_RETRY_PAUSE)
        return {"detail": f"Network {device_id} stopped successfully"}


def _release_leftovers(manager: NetworkManager, device_id: str) -> None:
    """Stop what a failed start left on a device that is not active (REV-1); 503 / 1012 if it fails."""
    try:
        manager.release_device(device_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=domain_error(ApiErrorCode.STOP_INCOMPLETE, str(exc)),
            headers={"Retry-After": str(STOP_RETRY_AFTER)},
        ) from exc


_GET_RESPONSES: dict = {
    503: DEVICE_BUSY_RESPONSE,
    200: {
        "description": (
            "Network status in sections: `reservation`, `radio`, `wifi`, `ip`, `internet`, "
            "`captive_portal` and `clients`. While the network is not running, or while the "
            "watchdog restores it, only `interface`, `active`, `runtime_state` and "
            "`reservation` are set and the sections are null."
        ),
        "content": {"application/json": {"examples": {
            "active": {
                "summary": "Active 5 GHz network at 80 MHz with Internet and two clients",
                "value": _ACTIVE_EXAMPLE,
            },
            "restoring_ap": {"value": {
                "interface": "wlan0", "active": False, "runtime_state": "restoring_ap",
                "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 54},
            }},
            "restoring_dhcp": {"value": {
                "interface": "wlan0", "active": True, "runtime_state": "restoring_dhcp",
                "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 53},
            }},
            "dhcp_failed": {"value": {
                "interface": "wlan0", "active": True, "runtime_state": "dhcp_failed",
                "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 51},
            }},
            "restore_failed": {
                "summary": "AP restart failed; the watchdog retries with backoff",
                "value": {
                "interface": "wlan0", "active": False, "runtime_state": "restore_failed",
                "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 3300},
            },
            },
            "captive_portal": {
                "summary": "Active network with a captive portal",
                "value": {
                    "interface": "wlan0", "active": True, "runtime_state": None,
                    "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 3540},
                    "radio": {
                        "band": "2.4ghz", "channel": 6,
                        "channel_width": {"requested": 20, "reported": 20},
                        "wifi_generation": 4,
                        "tx_power": {"requested_level": 4, "reported_level": 4, "reported_dbm": 20.0},
                    },
                    "wifi": {
                        "ssid": "CaptiveTest", "hidden": False,
                        "security": {"encryption": "wpa2", "password": "testpass123"},
                    },
                    "ip": {
                        "subnet": "192.168.120.0/24", "gateway": "192.168.120.1",
                        "dhcp_range": {"start": "192.168.120.10", "end": "192.168.120.250"},
                        "dns_server": "192.168.10.21",
                    },
                    "internet": {"enabled": True},
                    "captive_portal": {"enabled": True, "url": "http://192.168.120.1:8081/"},
                    "clients": [
                        {"mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.120.23", "captive_authorized": True},
                        {"mac": "aa:bb:cc:dd:ee:02", "ip": "192.168.120.57", "captive_authorized": False},
                    ],
                },
            },
        }}},
    },
    401: {"description": "Unauthorized (missing or invalid auth token)"},
    404: {"description": "Reservation not found or expired"},
}


@router.get(
    "/{reservation_id}/network",
    response_model=NetworkResponse,
    responses=_GET_RESPONSES,
)
def get_network(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Get complete network configuration, status, DHCP info, and connected clients.

    Requires a valid reservation token.
    During runtime restoration, returns the current `runtime_state` without
    waiting for the radio. A quarantined network's former ID returns 404.

    The answer is grouped in sections (`reservation`, `radio`, `wifi`, `ip`,
    `internet`, `captive_portal`, `clients`); they are null while the network
    is not running. `wifi.security.password` is returned so that test devices
    can be connected.
    """
    job = manager.start_job(reservation)
    if job is not None:
        # Answered without waiting for the device, which the start holds.
        return _state_response(reservation, job.state, job.error)
    runtime_state = manager.watchdog.state(reservation)
    if runtime_state in ("restoring_ap", "restoring_dhcp"):
        # Answered without waiting for the device, which the restore holds.
        return _state_response(reservation, runtime_state, active=runtime_state == "restoring_dhcp")
    with hold_reservation(reservation_mgr, reservation):
        return _network_response(manager, reservation)


def _network_response(manager: NetworkManager, reservation: Reservation) -> NetworkResponse:
    """`GET .../network` for a reservation whose device the caller holds."""
    device_id = reservation.device_id
    st = manager.get_status(device_id)
    if not st:
        raise HTTPException(status_code=404, detail=UNKNOWN_ANTENNA)
    st.expires_at = format_utc_timestamp(reservation.expires_at)
    st.expires_in = reservation.expires_in
    runtime_state = manager.watchdog.state(reservation) or (
        "stop_failed" if manager.stop_failed(device_id) else None
    )
    st = st.model_copy(update={"runtime_state": runtime_state})
    response = NetworkResponse.from_status(st, dns_server=manager.config.dns_server)
    response.restarts = _restarts(reservation)
    return response


def _restarts(reservation: Reservation) -> RestartsInfo:
    return RestartsInfo(
        ap=reservation.ap_restarts, dhcp=reservation.dhcp_restarts,
        last_at=format_utc_timestamp(reservation.last_restart_at),
        last_reason=reservation.last_restart_reason,
    )
