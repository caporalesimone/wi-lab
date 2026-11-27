"""What Wi-Lab knows about a running network (ARCH-3).

Kept apart from the API model NetworkStatus: the manager stores an
ActiveNetwork and builds a fresh NetworkStatus for each answer, so a read never
changes the stored state.
"""

import time
from dataclasses import dataclass

from ..models import NetworkCreateRequest, NetworkStatus


@dataclass
class ActiveNetwork:
    """A network started by NetworkManager.start_network.

    `request` is the create request as received; what can change afterwards
    (Internet access, TX power level) lives in its own fields.
    """

    interface: str
    request: NetworkCreateRequest
    subnet: str | None
    internet_enabled: bool   # the create's value resolved against the default, then toggled
    tx_power_level: int      # the create's level, then PUT .../tx-power
    captive_portal_url: str | None = None
    expires_at: str | None = None    # shown expiry (UTC, RFC 3339)
    deadline: float | None = None    # monotonic expiry (STAB-5); None: no expiry
    active: bool = True
    radio_channel: int | None = None   # the channel after a radar moved the AP, None if unmoved (REV-12)

    # Settings that cannot change while the network runs: read from the request.
    @property
    def ssid(self) -> str:
        return self.request.ssid

    @property
    def channel(self) -> int:
        return self.request.channel

    @property
    def band(self) -> str:
        return self.request.band

    @property
    def password(self) -> str | None:
        return self.request.password

    @property
    def encryption(self) -> str:
        return self.request.encryption

    @property
    def hidden(self) -> bool:
        return self.request.hidden

    @property
    def captive_portal(self) -> bool:
        return self.request.captive_portal

    @property
    def channel_width(self) -> int:
        return self.request.channel_width

    @property
    def wifi_generation(self) -> int:
        return self.request.wifi_generation

    @property
    def enable_generation_fallback(self) -> bool:
        return self.request.enable_generation_fallback

    @property
    def enable_ht_vht_capab(self) -> bool:
        return self.request.enable_ht_vht_capab

    def expired(self, now: float) -> bool:
        return self.deadline is not None and self.deadline < now

    def expires_in(self) -> int | None:
        """Seconds left before the expiry; None without one."""
        return None if self.deadline is None else max(0, int(self.deadline - time.monotonic()))

    def restart_request(self) -> NetworkCreateRequest:
        """The request that starts this network again as it runs now (watchdog restore).

        Internet access and TX power keep their current values, not the create's.
        """
        return self.request.model_copy(update={
            "internet_enabled": self.internet_enabled, "tx_power_level": self.tx_power_level,
        })

    def status(self) -> NetworkStatus:
        """The API view of the stored settings, without the live radio and DHCP reads."""
        req = self.request
        return NetworkStatus(
            interface=self.interface,
            active=self.active,
            ssid=req.ssid,
            channel=self.radio_channel or req.channel,
            password=req.password,
            encryption=req.encryption,
            band=req.band,
            hidden=req.hidden,
            channel_width=req.channel_width,
            wifi_generation=req.wifi_generation,
            enable_generation_fallback=req.enable_generation_fallback,
            enable_ht_vht_capab=req.enable_ht_vht_capab,
            subnet=self.subnet,
            internet_enabled=self.internet_enabled,
            captive_portal=req.captive_portal,
            captive_portal_url=self.captive_portal_url,
            tx_power_level=self.tx_power_level,
            expires_at=self.expires_at,
            expires_in=self.expires_in(),
        )
