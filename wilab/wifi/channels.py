"""WiFi channel information manager with in-memory caching.

Queries ``iw phy<N> channels`` to build a per-interface list of supported
channels, separated by band (2.4 GHz / 5 GHz).  Results are cached in
memory; a refusal is checked again on a fresh reading (BUG-4), and a reading
older than the last ``invalidate()`` is never cached (REV-12).

Design decision – disabled channels:
    ``iw`` reports some channels as ``(disabled)`` without a power value.
    Channels marked ``No IR`` (no initiate radiation) are also treated as
    disabled because they cannot be used in AP mode.
    Both cases are stored with ``max_power_dbm = 0.0`` and
    ``    disabled = True``. The same applies to radar-detection (DFS) channels of
    an antenna with ``show_dfs_channels: false``.  Consumers should check the ``disabled`` flag
    before using ``max_power_dbm``.
"""

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from ..network.commands import CommandError, execute_iw

logger = logging.getLogger(__name__)

# ---- Constants ----

_BAND_2_4_MAX_FREQ = 2500  # MHz – everything below is 2.4 GHz
_BAND_5_MIN_FREQ = 5000    # MHz – 5 GHz starts here...
_BAND_5_MAX_FREQ = 5925    # MHz – ...and ends before here: 6 GHz (5955+) is not offered

# Standard WiFi channel sets for static (hardware-independent) validation.
VALID_CHANNELS_24GHZ = frozenset(range(1, 15))  # 1–14
VALID_CHANNELS_5GHZ = (
    frozenset(range(36, 65, 4))     # UNII-1: 36, 40, 44, 48
    | frozenset(range(52, 65, 4))   # UNII-2: 52, 56, 60, 64
    | frozenset(range(100, 145, 4)) # UNII-2 Extended: 100–144
    | frozenset(range(149, 178, 4)) # UNII-3: 149–177
)


class FieldError(ValueError):
    """A refused network setting; `field` is its name in the flat create request.

    The API turns it into the field's path in the body (`radio.channel_width: ...`).
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def is_dfs_channel(band: str, channel: int) -> bool:
    """True for a 5 GHz channel that needs a radar check before use (UNII-2 and 2e: 52-144)."""
    return band == "5ghz" and 52 <= channel <= 144


def is_valid_channel_for_band(channel: int, band: str) -> bool:
    """Check whether *channel* is a standard WiFi channel for *band*.

    This is a hardware-independent check against well-known channel numbers.
    Use :meth:`ChannelManager.validate_channel` for hardware-aware validation.
    """
    if band == "2.4ghz":
        return channel in VALID_CHANNELS_24GHZ
    if band == "5ghz":
        return channel in VALID_CHANNELS_5GHZ
    raise ValueError(f"Unknown band: {band}")


# 5 GHz channel blocks (HAP-11): the 20 MHz channels that make up one 40 or 80 MHz
# channel, by first channel. A channel outside every block cannot use that width.
_BLOCKS_5GHZ = {
    40: tuple(range(36, 65, 8)) + tuple(range(100, 141, 8)) + tuple(range(149, 174, 8)),
    80: (36, 52, 100, 116, 132, 149, 165),
}
# 2.4 GHz channels whose 40 MHz secondary channel (channel ± 4) exists in the band.
_MAX_CHANNEL_24GHZ_40MHZ = 13


@dataclass(frozen=True)
class ChannelLayout:
    """Where a channel of a given width sits (HAP-11)."""
    channels: tuple[int, ...]       # every 20 MHz channel the network occupies
    center: int | None = None       # center channel index, for 40 and 80 MHz
    secondary_above: bool | None = None  # HT40+ (True) or HT40- (False), for 40 MHz and more


def channel_layouts(band: str, channel: int, width: int) -> list[ChannelLayout]:
    """The possible layouts of a *width* MHz channel with primary *channel*.

    5 GHz has one fixed block per channel; on 2.4 GHz the secondary channel can be
    above or below (both listed, above first). Raises ValueError for an
    impossible combination (for example channel 165 at 80 MHz).
    """
    if width == 20:
        return [ChannelLayout((channel,))]
    if band == "2.4ghz":
        if width != 40:
            raise FieldError("channel_width", f"{width} MHz is not available on 2.4 GHz (only 20 or 40 MHz)")
        layouts = []
        if channel + 4 <= _MAX_CHANNEL_24GHZ_40MHZ:
            layouts.append(ChannelLayout((channel, channel + 4), channel + 2, True))
        if channel - 4 >= 1 and channel <= _MAX_CHANNEL_24GHZ_40MHZ:
            layouts.append(ChannelLayout((channel - 4, channel), channel - 2, False))
        if not layouts:
            raise FieldError("channel_width", f"Channel {channel} cannot be used at 40 MHz on 2.4 GHz")
        return layouts
    span = width // 20
    first = next(
        (start for start in _BLOCKS_5GHZ.get(width, ()) if start <= channel < start + 4 * span),
        None,
    )
    if first is None:
        raise FieldError("channel_width", f"Channel {channel} cannot be used at {width} MHz on 5 GHz")
    channels = tuple(range(first, first + 4 * span, 4))
    # HT40 pair inside the block: the lower channel of a pair has its secondary above.
    above = (channel - first) // 4 % 2 == 0
    return [ChannelLayout(channels, first + 2 * (span - 1), above)]


@dataclass(frozen=True)
class BandCapabilities:
    """What one band of a radio can do in AP mode, from `iw phy <phy> info` (HAP-11)."""
    ht40: bool = False   # HT20/HT40
    vht: bool = False    # 802.11ac, which always includes 80 MHz
    he: bool = False     # 802.11ax in AP mode
    he40: bool = False
    he80: bool = False


@dataclass(frozen=True)
class RadioCapabilities:
    """Encryption, channel widths and Wi-Fi generations a radio supports (HAP-10, HAP-11)."""
    tkip: bool = False
    bands: dict[str, BandCapabilities] = field(default_factory=dict)

    def encryptions(self) -> list[str]:
        values = ["open", "wpa2", "wpa3", "wpa2-wpa3"]
        return ["open", "wpa1", *values[1:]] if self.tkip else values

    def channel_widths(self, band: str) -> list[int]:
        caps = self.bands.get(band, BandCapabilities())
        widths = [20]
        if caps.ht40 or caps.he40:
            widths.append(40)
        if band == "5ghz" and (caps.vht or caps.he80):
            widths.append(80)
        return widths

    def wifi_generations(self, band: str) -> list[int]:
        caps = self.bands.get(band, BandCapabilities())
        generations = [4]
        if band == "5ghz" and caps.vht:
            generations.append(5)
        if caps.he:
            generations.append(6)
        return generations

    def summary(self) -> dict:
        """A compact form for the log line written when an antenna is read."""
        return {
            "encryptions": self.encryptions(),
            "channel_widths": {band: self.channel_widths(band) for band in ("2.4ghz", "5ghz")},
            "wifi_generations": {band: self.wifi_generations(band) for band in ("2.4ghz", "5ghz")},
        }

    def check(self, band: str, encryption: str, width: int, generation: int) -> None:
        """Raise ValueError when the radio cannot run this combination."""
        if encryption not in self.encryptions():
            raise FieldError("encryption", f"{encryption} is not supported on this antenna")
        if width not in self.channel_widths(band):
            raise FieldError("channel_width", f"channel_width {width} MHz is not supported on this antenna for band {band}")
        if generation not in self.wifi_generations(band):
            raise FieldError(
                "wifi_generation", f"wifi_generation {generation} is not supported on this antenna for band {band}"
            )
        caps = self.bands.get(band, BandCapabilities())
        if generation == 6 and width == 40 and not caps.he40:
            raise FieldError("wifi_generation", f"802.11ax at 40 MHz is not supported on this antenna for band {band}")
        if generation == 6 and width == 80 and not caps.he80:
            raise FieldError("wifi_generation", "802.11ax at 80 MHz is not supported on this antenna")
        if generation == 5 and width == 80 and not caps.vht:
            raise FieldError("wifi_generation", "802.11ac at 80 MHz is not supported on this antenna")
        if width == 40 and generation == 4 and not caps.ht40:
            raise FieldError("channel_width", f"802.11n at 40 MHz is not supported on this antenna for band {band}")


def parse_phy_capabilities(output: str) -> RadioCapabilities:
    """Parse `iw phy <phy> info` into the AP capabilities Wi-Lab uses.

    A band is identified by its first frequency (below 2500 MHz: 2.4 GHz, from
    5000 MHz: 5 GHz; 6 GHz is ignored). HE counts only in an `HE Iftypes` block
    that lists AP.
    """
    bands: dict[str, BandCapabilities] = {}
    tkip = False
    flags: dict[str, bool] | None = None
    band: str | None = None
    he_ap = False

    def flush() -> None:
        if flags is not None and band is not None and band not in bands:
            bands[band] = BandCapabilities(**flags)

    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"Band \d+:", line):
            flush()
            flags, band, he_ap = dict.fromkeys(("ht40", "vht", "he", "he40", "he80"), False), None, False
            continue
        if line.startswith("* TKIP"):
            tkip = True
        if not raw.startswith("\t\t") and not raw.startswith("        "):
            # Back at the top level of the phy (for example "Supported Ciphers:").
            flush()
            flags, band, he_ap = None, None, False
            continue
        if flags is None:
            continue
        if line.startswith("HE Iftypes:"):
            he_ap = "AP" in re.split(r"[\s,]+", line.split(":", 1)[1])
            flags["he"] = flags["he"] or he_ap
        elif line.startswith(("Bitrates", "Frequencies", "VHT Capabilities", "EHT Iftypes")):
            he_ap = False
        if line == "HT20/HT40":
            flags["ht40"] = True
        elif line.startswith("VHT Capabilities"):
            flags["vht"] = True
        elif he_ap and line.startswith("HE40"):
            flags["he40"] = True
            flags["he80"] = flags["he80"] or "HE80" in line
        if band is None and (match := re.match(r"\* ([\d.]+) MHz", line)):
            frequency = float(match[1])
            band = "2.4ghz" if frequency < _BAND_2_4_MAX_FREQ else (
                "5ghz" if _BAND_5_MIN_FREQ <= frequency < _BAND_5_MAX_FREQ else "other"
            )
    flush()
    bands.pop("other", None)
    return RadioCapabilities(tkip=tkip, bands=bands)


def set_regulatory_domain(country_code: str) -> None:
    """Set the WiFi regulatory domain via ``iw reg set``.

    Should be called before populating the channel cache so that
    ``iw phy channels`` reports the correct flags for the country.
    """
    try:
        execute_iw(["reg", "set", country_code])
        logger.info("Regulatory domain set to %s", country_code)
    except Exception as exc:
        logger.warning("Failed to set regulatory domain to %s: %s", country_code, exc)


# ETSI weather-radar channels need a 10-minute radar check (CAC) before the AP
# may transmit: longer than the start can wait, so they are never offered (HAP-9).
LONG_CAC_CHANNELS = frozenset({120, 124, 128})


def _long_cac(channel: int, frequency_mhz: int) -> bool:
    return channel in LONG_CAC_CHANNELS and _BAND_5_MIN_FREQ <= frequency_mhz < _BAND_5_MAX_FREQ


# ---- Data classes ----


@dataclass(frozen=True)
class ChannelInfo:
    """A single WiFi channel."""
    channel: int
    frequency_mhz: int
    max_power_dbm: float
    disabled: bool
    requires_dfs: bool = False


@dataclass
class InterfaceChannels:
    """All supported channels for one physical interface, split by band."""
    interface: str
    channels_24ghz: list[ChannelInfo] = field(default_factory=list)
    channels_5ghz: list[ChannelInfo] = field(default_factory=list)
    capabilities: RadioCapabilities = field(default_factory=RadioCapabilities)


@dataclass(frozen=True)
class ChannelOption:
    """A channel a create can use, with the widths it can be used at (Antennas API)."""
    info: ChannelInfo
    channel_widths: tuple[int, ...]


@dataclass(frozen=True)
class BandOptions:
    """What a create can ask on one band: widths per Wi-Fi generation, usable channels."""
    wifi_generations: dict[int, list[int]]
    channels: list[ChannelOption]


def band_options(info: InterfaceChannels, band: str) -> BandOptions:
    """The choices :meth:`ChannelManager.validate_network` accepts on *band*.

    A channel is listed when it is enabled (DFS channels only with ``show_dfs_channels``);
    a width when every 20 MHz channel of one of its layouts is enabled. The rules
    match the create's, so a choice built from these lists is not refused.
    """
    caps = info.capabilities
    pool = info.channels_24ghz if band == "2.4ghz" else info.channels_5ghz
    enabled = {c.channel for c in pool if not c.disabled}
    widths = caps.channel_widths(band)

    def fits(channel: int, width: int) -> bool:
        try:
            layouts = channel_layouts(band, channel, width)
        except ValueError:
            return False
        return any(all(sub in enabled for sub in layout.channels) for layout in layouts)

    generations: dict[int, list[int]] = {}
    for generation in caps.wifi_generations(band):
        allowed = []
        for width in widths:
            if width == 80 and generation == 4:   # 80 MHz needs 802.11ac or 802.11ax
                continue
            try:
                caps.check(band, "open", width, generation)
            except ValueError:
                continue
            allowed.append(width)
        generations[generation] = allowed
    channels = [
        ChannelOption(c, tuple(w for w in widths if fits(c.channel, w)))
        for c in pool
        if not c.disabled and is_valid_channel_for_band(c.channel, band)
    ]
    return BandOptions(generations, channels)


# ---- Manager ----

class ChannelManager:
    """Resolves and caches WiFi channel information per interface.

    Thread-safe: the internal cache is protected by a lock so that
    concurrent API requests don't trigger duplicate ``iw`` queries.
    """

    def __init__(self, *, show_dfs_channels: Callable[[str], bool] | None = None) -> None:
        # Per antenna (`antennas[].show_dfs_channels`): whether its DFS channels are usable.
        self._show_dfs_channels = show_dfs_channels or (lambda interface: True)
        self._cache: dict[str, InterfaceChannels] = {}
        # Bumped by invalidate() (REV-12): a reading started before it is not cached.
        self._generation = 0
        self._lock = threading.Lock()

    # -- public API --

    def get_channels(self, interface: str) -> InterfaceChannels:
        """Return channel info for *interface*, querying ``iw`` only on first call."""
        with self._lock:
            if interface in self._cache:
                return self._cache[interface]
            generation = self._generation

        # Resolve outside lock to avoid blocking other interfaces.
        channels = self._resolve_channels(interface)

        with self._lock:
            if self._generation != generation:
                # invalidate() ran meanwhile: this reading may predate it, use it once
                # without caching it.
                return channels
            # Another thread may have filled the cache in the meantime.
            if interface not in self._cache:
                self._cache[interface] = channels
            return self._cache[interface]

    def invalidate(self, interface: str | None = None) -> None:
        """Drop cached data.  If *interface* is ``None``, flush everything."""
        with self._lock:
            self._generation += 1
            if interface is None:
                self._cache.clear()
            else:
                self._cache.pop(interface, None)

    def validate_channel(self, interface: str, channel: int, band: str) -> None:
        """Validate *channel* against the hardware capabilities of *interface*.

        Raises :class:`ValueError` if the channel is not supported or disabled.
        A refusal from the cache is checked once more against a fresh `iw`
        reading (BUG-4): the list may have been read before the regulatory
        domain was applied, when 5 GHz channels still show "no IR".
        """
        try:
            self._validate(interface, channel, band)
        except ValueError:
            self.invalidate(interface)
            self._validate(interface, channel, band)

    def validate_network(
        self, interface: str, band: str, channel: int, width: int, generation: int, encryption: str,
    ) -> ChannelLayout:
        """Check a network against the radio (HAP-10, HAP-11) and return its channel layout.

        Every 20 MHz channel of a 40 or 80 MHz channel must be usable, so DFS
        channels inside a wide channel follow the antenna's ``show_dfs_channels``. Like
        :meth:`validate_channel`, a refusal is checked again on a fresh reading.
        """
        try:
            return self._validate_network(interface, band, channel, width, generation, encryption)
        except ValueError:
            self.invalidate(interface)
            return self._validate_network(interface, band, channel, width, generation, encryption)

    def _validate_network(
        self, interface: str, band: str, channel: int, width: int, generation: int, encryption: str,
    ) -> ChannelLayout:
        self._validate(interface, channel, band)
        self.get_channels(interface).capabilities.check(band, encryption, width, generation)
        error: ValueError | None = None
        for layout in channel_layouts(band, channel, width):
            try:
                for sub in layout.channels:
                    self._validate(interface, sub, band)
            except ValueError as exc:
                error = error or exc
                continue
            return layout
        assert error is not None
        raise FieldError("channel_width", f"{width} MHz on channel {channel} is not available: {error}")

    def _validate(self, interface: str, channel: int, band: str) -> None:
        info = self.get_channels(interface)
        if band == "2.4ghz":
            pool = info.channels_24ghz
        elif band == "5ghz":
            pool = info.channels_5ghz
        else:
            raise FieldError("band", f"Unknown band: {band}")

        if band == "5ghz" and channel in LONG_CAC_CHANNELS:
            raise FieldError(
                "channel", f"Channel {channel} requires a 10-minute radar check (weather radar) "
                "and is not supported",
            )
        match = next((c for c in pool if c.channel == channel), None)
        if match is None:
            raise FieldError(
                "channel", f"Channel {channel} is not supported on {interface} for band {band}"
            )
        if match.disabled:
            if match.requires_dfs and not self._show_dfs_channels(interface):
                raise FieldError(
                    "channel", f"DFS channel {channel} is not offered on {interface} (show_dfs_channels: false)",
                )
            raise FieldError(
                "channel", f"Channel {channel} is disabled on {interface} for band {band}"
                " (regulatory domain restriction)"
            )

    # -- internals --

    @staticmethod
    def _get_phy_for_interface(interface: str) -> str:
        """Determine the wiphy index for *interface* via ``iw <dev> info``."""
        info = execute_iw([interface, "info"])
        for line in info.splitlines():
            if "wiphy" in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    return parts[1]
        raise ValueError(f"Cannot determine wiphy for interface {interface}")

    @staticmethod
    def _parse_iw_phy_output(
        output: str, *, show_dfs_channels: bool = False,
    ) -> list[ChannelInfo]:
        """Parse the output of ``iw phy<N> channels`` into a list of channels.

        Radar detection may be marked on the frequency line or on its own line.
        """
        # Matches both active and disabled header lines
        header_re = re.compile(
            r"\*\s+([\d.]+)\s+MHz\s+\[(\d+)\](?:\s+\(disabled\))?"
        )
        power_re = re.compile(r"Maximum TX power:\s+([\d.]+)\s+dBm")

        channels: list[ChannelInfo] = []
        current_freq: int | None = None
        current_chan: int | None = None
        current_disabled = False
        current_power: float = 0.0
        current_no_ir = False
        current_dfs = False

        def _flush() -> None:
            nonlocal current_freq, current_chan, current_disabled
            nonlocal current_power, current_no_ir, current_dfs
            if current_freq is not None and current_chan is not None:
                disabled = (
                    current_disabled or current_no_ir or (current_dfs and not show_dfs_channels)
                    or _long_cac(current_chan, current_freq)
                )
                channels.append(ChannelInfo(
                    channel=current_chan,
                    frequency_mhz=current_freq,
                    max_power_dbm=0.0 if disabled else current_power,
                    disabled=disabled,
                    requires_dfs=current_dfs,
                ))
            current_freq = None
            current_chan = None
            current_disabled = False
            current_power = 0.0
            current_no_ir = False
            current_dfs = False

        for line in output.splitlines():
            hm = header_re.search(line)
            if hm:
                _flush()
                current_freq = int(float(hm.group(1)))
                current_chan = int(hm.group(2))
                current_disabled = "(disabled)" in line
            if current_freq is not None:
                flags = line.lower()
                pm = power_re.search(line)
                if pm:
                    current_power = float(pm.group(1))
                if "no ir" in flags:
                    current_no_ir = True
                if "radar detection" in flags:
                    current_dfs = True
        _flush()
        return channels

    def _resolve_channels(self, interface: str) -> InterfaceChannels:
        """Query ``iw`` and split results into 2.4 GHz / 5 GHz bands."""
        phy = self._get_phy_for_interface(interface)
        output = execute_iw(["phy" + phy, "channels"])
        all_channels = self._parse_iw_phy_output(output, show_dfs_channels=self._show_dfs_channels(interface))

        ch_24: list[ChannelInfo] = []
        ch_5: list[ChannelInfo] = []
        for ch in all_channels:
            if ch.frequency_mhz < _BAND_2_4_MAX_FREQ:
                ch_24.append(ch)
            elif _BAND_5_MIN_FREQ <= ch.frequency_mhz < _BAND_5_MAX_FREQ:
                ch_5.append(ch)
            # Anything else (6 GHz) is ignored: Wi-Lab cannot create a 6 GHz
            # network, and 6 GHz reuses channel numbers such as 149.

        try:
            capabilities = parse_phy_capabilities(execute_iw(["phy" + phy, "info"]))
        except CommandError as exc:
            # Without the reading only 20 MHz, 802.11n and the encryptions every
            # radio has are offered; the next invalidation reads it again.
            logger.warning("Cannot read capabilities of %s: %s", interface, exc)
            capabilities = RadioCapabilities()

        result = InterfaceChannels(
            interface=interface,
            channels_24ghz=ch_24,
            channels_5ghz=ch_5,
            capabilities=capabilities,
        )
        logger.info(
            "Resolved %d channels for %s (2.4 GHz: %d, 5 GHz: %d)",
            len(all_channels), interface, len(ch_24), len(ch_5),
        )
        logger.info("Capabilities of %s: %s", interface, capabilities.summary())
        return result
