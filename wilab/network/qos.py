"""QoS traffic control management using tc (HTB + IFB)."""

import logging
from dataclasses import dataclass
from typing import Dict, Optional

from .commands import execute_tc, execute_command, CommandError

logger = logging.getLogger(__name__)

_SENTINEL = object()  # marker for "field not provided in request"

# Maximum rate used when quality-only (no speed limit) to keep HTB tree
_UNLIMITED_RATE_KBIT = 1_000_000


@dataclass
class _InterfaceQosState:
    """In-memory state for a single physical interface."""

    interface: str
    ifb_device: Optional[str] = None
    download_speed_kbit: Optional[int] = None
    upload_speed_kbit: Optional[int] = None
    download_quality: Optional[int] = None
    upload_quality: Optional[int] = None
    # Whether the HTB tree is installed on the device
    htb_installed: bool = False
    ifb_htb_installed: bool = False

    @property
    def active(self) -> bool:
        return any([
            self.download_speed_kbit,
            self.upload_speed_kbit,
            self.download_quality is not None,
            self.upload_quality is not None,
        ])


class QosManager:
    """Manages per-interface QoS rules via Linux tc."""

    def __init__(self) -> None:
        self._state: Dict[str, _InterfaceQosState] = {}
        self._ifb_counter = 0
        logger.info("QosManager initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_qos(
        self,
        interface: str,
        download_speed_kbit: object = _SENTINEL,
        upload_speed_kbit: object = _SENTINEL,
    ) -> None:
        """Apply or update bandwidth throttling on *interface*.

        Each parameter follows the partial-update semantic:
        - ``_SENTINEL`` (default / omitted): keep current value unchanged.
        - ``None``: reset to unlimited.
        - ``int``: apply the new limit.
        """
        state = self._get_or_create(interface)

        # Resolve values --------------------------------------------------
        dl = self._resolve(download_speed_kbit, state.download_speed_kbit)
        ul = self._resolve(upload_speed_kbit, state.upload_speed_kbit)

        # Apply download (egress on physical interface) --------------------
        self._apply_download_throttle(interface, state, dl)

        # Apply upload (egress on IFB device) ------------------------------
        self._apply_upload_throttle(interface, state, ul)

        # Persist state ----------------------------------------------------
        state.download_speed_kbit = dl
        state.upload_speed_kbit = ul

        # If nothing is active anymore, tear down trees
        if not state.active:
            self._teardown(interface, state)

    def clear_qos(self, interface: str) -> None:
        """Remove all QoS rules from *interface*."""
        state = self._state.get(interface)
        if state is None:
            return
        self._teardown(interface, state)
        state.download_speed_kbit = None
        state.upload_speed_kbit = None
        state.download_quality = None
        state.upload_quality = None
        logger.info(f"QoS cleared for {interface}")

    def get_status(self, interface: str) -> Optional[_InterfaceQosState]:
        return self._state.get(interface)

    # ------------------------------------------------------------------
    # Download (egress on physical interface)
    # ------------------------------------------------------------------

    def _apply_download_throttle(
        self, interface: str, state: _InterfaceQosState, rate_kbit: Optional[int]
    ) -> None:
        if rate_kbit is None and state.download_speed_kbit is None:
            # Nothing to do and nothing was set
            return

        if rate_kbit is None:
            # Reset: remove HTB tree if no quality needs it
            if state.download_quality is None:
                self._remove_root_qdisc(interface)
                state.htb_installed = False
            else:
                # Quality still active – set unlimited rate
                self._ensure_htb(interface, state, direction="download")
                self._change_class_rate(interface, _UNLIMITED_RATE_KBIT)
            return

        # Set or update rate
        self._ensure_htb(interface, state, direction="download")
        self._change_class_rate(interface, rate_kbit)

    # ------------------------------------------------------------------
    # Upload (egress on IFB)
    # ------------------------------------------------------------------

    def _apply_upload_throttle(
        self, interface: str, state: _InterfaceQosState, rate_kbit: Optional[int]
    ) -> None:
        if rate_kbit is None and state.upload_speed_kbit is None:
            return

        if rate_kbit is None:
            if state.upload_quality is None:
                self._remove_ifb(interface, state)
            else:
                self._ensure_ifb(interface, state)
                ifb = state.ifb_device
                assert ifb is not None
                self._change_class_rate(ifb, _UNLIMITED_RATE_KBIT)
            return

        self._ensure_ifb(interface, state)
        ifb = state.ifb_device
        assert ifb is not None
        self._change_class_rate(ifb, rate_kbit)

    # ------------------------------------------------------------------
    # HTB tree management
    # ------------------------------------------------------------------

    def _ensure_htb(
        self, device: str, state: _InterfaceQosState, direction: str = "download"
    ) -> None:
        """Ensure HTB root qdisc + default class exist on *device*."""
        installed = state.htb_installed if direction == "download" else state.ifb_htb_installed
        if installed:
            return

        rate = _UNLIMITED_RATE_KBIT  # will be changed immediately after
        try:
            execute_tc(["qdisc", "add", "dev", device, "root", "handle", "1:", "htb", "default", "10"])
        except CommandError:
            # Tree may already exist – replace
            execute_tc(["qdisc", "replace", "dev", device, "root", "handle", "1:", "htb", "default", "10"])

        burst = self._calc_burst(rate)
        try:
            execute_tc([
                "class", "add", "dev", device, "parent", "1:", "classid", "1:10",
                "htb", "rate", f"{rate}kbit", "ceil", f"{rate}kbit", "burst", burst,
            ])
        except CommandError:
            execute_tc([
                "class", "change", "dev", device, "parent", "1:", "classid", "1:10",
                "htb", "rate", f"{rate}kbit", "ceil", f"{rate}kbit", "burst", burst,
            ])

        if direction == "download":
            state.htb_installed = True
        else:
            state.ifb_htb_installed = True
        logger.debug(f"HTB tree ensured on {device}")

    def _change_class_rate(self, device: str, rate_kbit: int) -> None:
        burst = self._calc_burst(rate_kbit)
        execute_tc([
            "class", "change", "dev", device, "parent", "1:", "classid", "1:10",
            "htb", "rate", f"{rate_kbit}kbit", "ceil", f"{rate_kbit}kbit", "burst", burst,
        ])
        logger.debug(f"HTB rate set to {rate_kbit}kbit on {device}")

    # ------------------------------------------------------------------
    # IFB management (for upload direction)
    # ------------------------------------------------------------------

    def _ensure_ifb(self, interface: str, state: _InterfaceQosState) -> None:
        """Ensure IFB device + ingress redirect exist for *interface*."""
        if state.ifb_device is not None:
            # IFB already allocated, just make sure HTB tree exists
            self._ensure_htb(state.ifb_device, state, direction="upload")
            return

        ifb = self._allocate_ifb()
        state.ifb_device = ifb

        try:
            execute_command(["modprobe", "ifb"])
        except CommandError as e:
            logger.warning(f"modprobe ifb failed (may already be loaded): {e}")

        # Bring IFB device up
        try:
            execute_command(["ip", "link", "add", ifb, "type", "ifb"])
        except CommandError:
            pass  # device may already exist
        execute_command(["ip", "link", "set", "dev", ifb, "up"])

        # Set up ingress redirect on physical interface
        try:
            execute_tc(["qdisc", "add", "dev", interface, "handle", "ffff:", "ingress"])
        except CommandError:
            pass  # ingress qdisc may already exist

        execute_tc([
            "filter", "add", "dev", interface, "parent", "ffff:",
            "protocol", "all", "u32", "match", "u32", "0", "0",
            "action", "mirred", "egress", "redirect", "dev", ifb,
        ])

        # Build HTB tree on IFB
        self._ensure_htb(ifb, state, direction="upload")
        logger.info(f"IFB {ifb} configured for upload shaping on {interface}")

    def _remove_ifb(self, interface: str, state: _InterfaceQosState) -> None:
        ifb = state.ifb_device
        if ifb is None:
            return
        try:
            execute_tc(["qdisc", "del", "dev", ifb, "root"])
        except CommandError:
            pass
        try:
            execute_command(["ip", "link", "set", "dev", ifb, "down"])
        except CommandError:
            pass
        try:
            execute_command(["ip", "link", "del", ifb])
        except CommandError:
            pass
        # Remove ingress qdisc from physical interface
        try:
            execute_tc(["qdisc", "del", "dev", interface, "ingress"])
        except CommandError:
            pass
        state.ifb_device = None
        state.ifb_htb_installed = False
        logger.debug(f"IFB removed for {interface}")

    def _allocate_ifb(self) -> str:
        name = f"ifb{self._ifb_counter}"
        self._ifb_counter += 1
        return name

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def _teardown(self, interface: str, state: _InterfaceQosState) -> None:
        self._remove_root_qdisc(interface)
        state.htb_installed = False
        self._remove_ifb(interface, state)

    def _remove_root_qdisc(self, device: str) -> None:
        try:
            execute_tc(["qdisc", "del", "dev", device, "root"])
        except CommandError:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve(value: object, current: Optional[int]) -> Optional[int]:
        """Resolve partial-update semantic for a single field."""
        if value is _SENTINEL:
            return current
        return value  # type: ignore[return-value]

    @staticmethod
    def _calc_burst(rate_kbit: int) -> str:
        """Calculate a sensible burst size for HTB."""
        burst_bytes = max(rate_kbit * 1000 // 8 // 10, 15000)
        return f"{burst_bytes}"

    def _get_or_create(self, interface: str) -> _InterfaceQosState:
        if interface not in self._state:
            self._state[interface] = _InterfaceQosState(interface=interface)
        return self._state[interface]
