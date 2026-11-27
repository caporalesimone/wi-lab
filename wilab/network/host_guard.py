"""Keep AP clients away from the Wi-Lab host itself (SEC-3).

Every network gets its own chain, `wilab-in-<net_id>`, in the IPv4 and IPv6
`filter` tables, jumped to from `INPUT` for packets that arrive on the AP
interface. A client may only reach what the network needs:

- DHCP (UDP 67);
- with the captive portal: DNS (UDP/TCP 53, answered by dnsmasq) and the
  portal page on the gateway;
- ICMP (ping the gateway), ICMPv6 (neighbour discovery).

Everything else (the Wi-Lab API, SSH, any other host service) is rejected.
Forwarded traffic (Internet, isolation) is not affected: it uses `FORWARD`.
"""

import logging
from collections.abc import Callable

from . import rules
from .commands import IPTABLES_LOCK_WAIT, CommandError, execute_command, execute_iptables, rule_exists

logger = logging.getLogger(__name__)

CHAIN_PREFIX = "wilab-in-"
JUMP_COMMENT_PREFIX = "wilab-guard-"
DNS_PORT = 53
DHCP_PORT = 67


def _ip6tables(args: list[str], *, quiet: bool = False) -> str:
    return execute_command(["ip6tables", "-w", IPTABLES_LOCK_WAIT, *args], quiet=quiet)


def chain(net_id: str) -> str:
    return f"{CHAIN_PREFIX}{net_id}"


def _jump(interface: str, net_id: str) -> list[str]:
    return [
        "INPUT", "-i", interface, "-m", "comment", "--comment", f"{JUMP_COMMENT_PREFIX}{net_id}",
        "-j", chain(net_id),
    ]


def _ipv4_rules(captive_port: int | None) -> list[list[str]]:
    rules = [["-p", "udp", "--dport", str(DHCP_PORT), "-j", "ACCEPT"]]
    if captive_port is not None:
        rules += [
            ["-p", "udp", "--dport", str(DNS_PORT), "-j", "ACCEPT"],
            ["-p", "tcp", "--dport", str(DNS_PORT), "-j", "ACCEPT"],
            ["-p", "tcp", "--dport", str(captive_port), "-j", "ACCEPT"],
        ]
    return [
        *rules,
        ["-p", "icmp", "-j", "ACCEPT"],
        ["-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset"],
        ["-j", "REJECT"],
    ]


def _ipv6_rules() -> list[list[str]]:
    return [
        ["-p", "ipv6-icmp", "-j", "ACCEPT"],
        ["-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset"],
        ["-j", "REJECT"],
    ]


class HostGuard:
    """Install, check and remove the per-network INPUT guard."""

    def __init__(self) -> None:
        self._guarded: dict[str, str] = {}  # net_id -> interface

    def add(self, interface: str, net_id: str, captive_port: int | None = None) -> None:
        """Guard the host from clients of `interface`. All or nothing: raises CommandError."""
        self._guarded[net_id] = interface  # tracked first, so a rollback removes partial rules
        name = chain(net_id)
        for run, rules in ((execute_iptables, _ipv4_rules(captive_port)), (_ip6tables, _ipv6_rules())):
            run(["-N", name])
            for rule in rules:
                run(["-A", name, *rule])
            # First in INPUT, so a host rule that accepts everything cannot come before it.
            run(["-I", "INPUT", "1", *_jump(interface, net_id)[1:]])
        logger.info("Host guard installed for %s (%s)", net_id, interface)

    def remove(self, net_id: str) -> None:
        """Remove the guard of one network; missing rules are not an error.

        A failed `-D`, `-F` or `-X` is checked against the firewall instead of
        its message (REV-4): iptables answers a missing chain with a different
        text on each backend ("Chain ... does not exist" with nf_tables,
        "Couldn't load target" with legacy). The work is done when neither the
        jump nor the chain is left.
        """
        interface = self._guarded.get(net_id)
        if interface is None:
            return
        name = chain(net_id)
        failed: list[str] = []
        for family, run in (("IPv4", execute_iptables), ("IPv6", _ip6tables)):
            errors: list[str] = []
            for args in (["-D", *_jump(interface, net_id)], ["-F", name], ["-X", name]):
                try:
                    run(args, quiet=True)
                except CommandError as exc:
                    errors.append(f"{' '.join(args[:2])}: {exc}")
            if errors and not self._gone(run, interface, net_id):
                failed.append(f"{family} {'; '.join(errors)}")
        if failed:
            raise CommandError(f"Cannot remove host guard for {net_id}: {'; '.join(failed)}")
        self._guarded.pop(net_id, None)

    @staticmethod
    def _gone(run: Callable[..., str], interface: str, net_id: str) -> bool:
        """Whether neither the jump nor the chain of a guard is left; False when unsure."""
        try:
            if rule_exists(run, _jump(interface, net_id), chain=[chain(net_id)]):
                return False
            run(["-S", chain(net_id)], quiet=True)
            return False   # the chain is still there
        except CommandError as exc:
            return exc.returncode == 1   # "No chain/target/match by that name"

    def problems(self, net_id: str) -> list[str]:
        """What is missing from the guard of a running network (WD-7)."""
        interface = self._guarded.get(net_id)
        if interface is None:
            return []
        found = []
        for family, run in (("IPv4", execute_iptables), ("IPv6", _ip6tables)):
            # A failed check raises (REV-3): the watchdog skips this round instead
            # of restoring a network whose guard may be in place.
            if not rule_exists(run, _jump(interface, net_id), chain=[chain(net_id)]):
                found.append(f"{family} host guard")
        return found

    def has(self, net_id: str) -> bool:
        return net_id in self._guarded

    @staticmethod
    def remove_stale() -> None:
        """Delete every Wi-Lab guard jump and chain left by a previous run. Never raises."""
        for run in (execute_iptables, _ip6tables):
            try:
                rules.delete_commented("INPUT", lambda c: c.startswith(JUMP_COMMENT_PREFIX), run=run)
                rules.delete_chains(lambda name: name.startswith(CHAIN_PREFIX), run=run)
            except (CommandError, ValueError) as exc:
                logger.error("Could not remove stale host guard rules: %s", exc)


def remove_stale_guards() -> None:
    """Startup hook: remove host guards left by a previous run."""
    HostGuard.remove_stale()
