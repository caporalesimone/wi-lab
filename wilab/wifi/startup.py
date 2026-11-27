"""One AP start attempt and the retries of a radio failure within one start (ARCH-1).

NetworkManager.start_network checks the request and the interface, then calls
run_startup; afterwards it sets the TX power and records the network.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv4Network
from typing import TYPE_CHECKING

from ..models import NetworkCreateRequest
from ..network.captive import CaptivePortal, CaptivePortalError
from ..network.commands import CommandError, execute_ip
from ..network.dhcp import DhcpServerError
from .channels import ChannelLayout
from .failures import FailureKind
from .hostapd import HostapdError
from .interface import interface_present

if TYPE_CHECKING:
    from .manager import NetworkManager

logger = logging.getLogger(__name__)

# Transient radio failures usually clear on an immediate new start, so the
# server retries during the create instead of handing the retry to the client.
STARTUP_ATTEMPTS = 3
# The attempts have no time budget (REV-5): the create runs in the background,
# so only the number of attempts and the reservation expiry limit them.
STARTUP_RETRY_DELAY = 1.0

# Stable names of the startup stages, shown as `error.stage` with start_failed (1013).
STARTUP_STAGES = {
    "start AP": "hostapd",
    "block Internet": "internet_block",
    "assign gateway IP": "gateway",
    "configure DHCP": "dhcp",
    "start captive portal": "captive_portal",
    "enable Internet": "nat",
    "isolate network": "isolation",
    "protect host": "host_guard",
}


class StartupFailure(ValueError):
    """A network start that failed; *kind* is set once, where the start fails (ARCH-2)."""

    def __init__(
        self, message: str, *, kind: FailureKind = FailureKind.CONFIGURATION,
        stage: str | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.stage = stage   # one of STARTUP_STAGES' values, or "interface"

    # Derived from kind for existing readers; new code reads kind.
    @property
    def radio(self) -> bool:
        return self.kind.radio

    @property
    def cleanup_failed(self) -> bool:
        return self.kind.cleanup_failed


def _cleanup_failed(radio: bool) -> FailureKind:
    return FailureKind.RADIO_CLEANUP_FAILED if radio else FailureKind.CLEANUP_FAILED


@dataclass(frozen=True)
class RetryPolicy:
    """How often one start tries again after a radio failure of its AP (HAP-3, REV-5).

    Only the internal retry of NetworkManager.start_network uses it. The create
    route (paused rounds, then quarantine) and the watchdog (backoff across its
    ticks) keep their own schedules of later starts and choose, with
    `allow_internal_retry`, whether a start retries with this policy.
    """

    attempts: int
    delay: float

    @classmethod
    def internal(cls) -> "RetryPolicy":
        """The internal retry, read when a start begins (tests change the module values)."""
        return cls(STARTUP_ATTEMPTS, STARTUP_RETRY_DELAY)

    @classmethod
    def single(cls) -> "RetryPolicy":
        """No internal retry: the caller retries itself."""
        return cls(1, 0.0)

    def wait_for_retry(
        self, attempt: int, deadline: float | None, cancelled: Callable[[], bool] | None,
    ) -> bool:
        """After a retryable failure of *attempt*, wait; True to try again.

        No retry after the last attempt, nor when the pause would pass *deadline*
        (monotonic, STAB-5), nor if the start was cancelled or expired meanwhile.
        """
        if attempt >= self.attempts:
            return False
        if deadline is not None and time.monotonic() + self.delay >= deadline:
            return False
        time.sleep(self.delay)
        return (
            not (cancelled is not None and cancelled())
            and (deadline is None or time.monotonic() < deadline)
        )


@dataclass(frozen=True)
class StartPlan:
    """What every attempt of one start sets up, decided before the first one."""

    device_id: str
    interface: str
    request: NetworkCreateRequest
    subnet: str
    internet_enabled: bool
    layout: ChannelLayout
    cancelled: Callable[[], bool] | None = None


class StartAttempt:
    """One pass through the startup stages; `stage` names the stage running."""

    def __init__(self, manager: "NetworkManager", plan: StartPlan) -> None:
        self._manager = manager
        self._plan = plan
        self.stage = "start AP"

    def run(self) -> None:
        mgr, plan, req = self._manager, self._plan, self._plan.request
        device_id, interface, subnet = plan.device_id, plan.interface, plan.subnet
        net = IPv4Network(subnet)
        gateway = f"{net[1]}/{net.prefixlen}"
        if not plan.internet_enabled:
            self.stage = "block Internet"
            try:
                with mgr._firewall_lock:
                    mgr.nat_manager.block_internet(interface, device_id)
            except RuntimeError as exc:
                raise CommandError(str(exc)) from exc
        self.stage = "start AP"
        mgr.hostapd_manager.start(
            net_id=device_id,
            interface=interface,
            ssid=req.ssid,
            channel=req.channel,
            encryption=req.encryption,
            password=req.password,
            hidden=req.hidden,
            band=req.band,
            country_code=mgr.config.country_code,
            channel_width=req.channel_width,
            wifi_generation=req.wifi_generation,
            layout=plan.layout,
            **({"cancelled": plan.cancelled} if plan.cancelled is not None else {}),
        )
        self.stage = "assign gateway IP"
        execute_ip(["addr", "add", gateway, "dev", interface])
        logger.info("Gateway IP %s assigned to %s", gateway, interface)
        self.stage = "configure DHCP"
        mgr.dhcp_server.start(
            net_id=device_id,
            interface=interface,
            subnet=subnet,
            dns_server=mgr.config.dns_server,
            **({"captive_dns": True} if req.captive_portal else {}),
        )
        if req.captive_portal:
            self.stage = "start captive portal"
            portal = CaptivePortal(
                interface=interface, net_id=device_id, gateway=str(net[1]),
                context=lambda: mgr._portal_context(device_id),
                lookup_mac=lambda ip: mgr.clients.mac_of(device_id, ip),
                firewall_lock=mgr._firewall_lock,
                port=mgr.config.captive_portal_port,
            )
            # Tracked before start so a rollback removes partial rules.
            mgr.captive_portals[device_id] = portal
            portal.start()
        # NAT and isolation are part of the startup (NET-2): a network
        # never reports success without the firewall it claims.
        if plan.internet_enabled:
            self.stage = "enable Internet"
            try:
                with mgr._firewall_lock:
                    mgr.nat_manager.enable_nat(interface, device_id, subnet)
            except RuntimeError as exc:
                raise CommandError(str(exc)) from exc
            logger.info("NAT enabled for %s", device_id)
        self.stage = "isolate network"
        with mgr._firewall_lock:
            mgr.isolation_manager.add_network(subnet)
        logger.info("Isolation rules applied for %s (%s)", device_id, subnet)
        # The host itself is off limits to AP clients (SEC-3); part of the
        # startup like NAT and isolation, so it is never silently missing.
        self.stage = "protect host"
        running_portal = mgr.captive_portals.get(device_id)
        with mgr._firewall_lock:
            mgr.host_guard.add(
                interface, device_id,
                running_portal.port if running_portal is not None else None,
            )


def _failure(message: str, stage: str, kind: FailureKind) -> StartupFailure:
    return StartupFailure(message, kind=kind, stage=STARTUP_STAGES.get(stage))


def _roll_back(
    manager: "NetworkManager", plan: StartPlan, stage: str, message: str, radio: bool,
    cause: Exception,
) -> None:
    """Undo a failed attempt; if that fails too, the start ends as cleanup_failed."""
    try:
        manager.release_device(plan.device_id)
    except RuntimeError:
        logger.exception("Startup rollback failed for %s", plan.device_id)
        raise _failure(
            message, stage, _cleanup_failed(radio or not interface_present(plan.interface)),
        ) from cause


def run_startup(
    manager: "NetworkManager", plan: StartPlan, policy: RetryPolicy, deadline: float | None,
) -> None:
    """Run attempts until one succeeds; raise StartupFailure after rolling back the last."""
    device_id, interface = plan.device_id, plan.interface
    # A classified radio failure happened in this request (HAP-3): a later
    # attempt that fails while starting the AP keeps that classification.
    radio_seen = False
    for attempt_number in range(1, policy.attempts + 1):
        attempt = StartAttempt(manager, plan)
        try:
            attempt.run()
        except (HostapdError, CommandError, DhcpServerError, CaptivePortalError) as e:
            stage = attempt.stage
            logger.error("Failed to %s for %s: %s", stage, device_id, e)
            # Only hostapd tells a radio failure apart; every other cause is a stage failure.
            cause = e.kind if isinstance(e, HostapdError) else FailureKind.CONFIGURATION
            radio_seen = radio_seen or cause is FailureKind.TRANSIENT_RADIO
            radio = cause is FailureKind.TRANSIENT_RADIO or (radio_seen and stage == "start AP")
            message = f"Failed to {stage}: {e}"
            _roll_back(manager, plan, stage, message, radio, e)
            if not interface_present(interface):
                # Whatever hostapd reported, the netdev vanished under it: a
                # radio fault. An immediate internal retry cannot succeed
                # until the adapter re-enumerates, so leave it to the client.
                logger.warning(
                    "Interface %s disappeared during startup; treating it as a radio failure",
                    interface,
                )
                raise StartupFailure(
                    f"Failed to {stage}: interface {interface} disappeared ({e})",
                    kind=FailureKind.TRANSIENT_RADIO,
                ) from e

            if (
                stage == "start AP" and cause is FailureKind.TRANSIENT_RADIO
                and policy.wait_for_retry(attempt_number, deadline, plan.cancelled)
            ):
                logger.info(
                    "Retrying AP startup (attempt %d/%d) after %s on %s",
                    attempt_number + 1, policy.attempts, type(e).__name__, device_id,
                )
                continue
            raise _failure(
                message, stage, FailureKind.TRANSIENT_RADIO if radio else FailureKind.CONFIGURATION,
            ) from e
        except Exception as e:
            # Anything else (a bug, an OSError from a library, a KeyError) after
            # the AP may already be up: roll back all the same, or hostapd keeps
            # transmitting for a network nobody tracks (REV-1). Never retried.
            stage = attempt.stage
            logger.exception("Unexpected error during %s for %s", stage, device_id)
            message = f"Failed to {stage}: {e!r}"
            _roll_back(manager, plan, stage, message, False, e)
            raise _failure(message, stage, FailureKind.CONFIGURATION) from e
        else:
            if attempt_number > 1:
                logger.info("AP startup retry recovered %s", device_id)
            return
