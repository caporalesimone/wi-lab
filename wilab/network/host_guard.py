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
import shlex
from itertools import pairwise

from .commands import CommandError, execute_command, execute_iptables

logger = logging.getLogger(__name__)

CHAIN_PREFIX = "wilab-in-"
JUMP_COMMENT_PREFIX = "wilab-guard-"
DNS_PORT = 53
DHCP_PORT = 67


def _ip6tables(args: list[str]) -> str:
    return execute_command(["ip6tables", "-w", "5", *args])


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
        """Remove the guard of one network; missing rules are not an error."""
        interface = self._guarded.get(net_id)
        if interface is None:
            return
        name = chain(net_id)
        failed: list[str] = []
        for run in (execute_iptables, _ip6tables):
            for args in (["-D", *_jump(interface, net_id)], ["-F", name], ["-X", name]):
                try:
                    run(args)
                except CommandError as exc:
                    if "No chain" not in str(exc) and "does a matching rule exist" not in str(exc):
                        failed.append(f"{' '.join(args[:2])}: {exc}")
        if failed:
            raise CommandError(f"Cannot remove host guard for {net_id}: {'; '.join(failed)}")
        self._guarded.pop(net_id, None)

    def problems(self, net_id: str) -> list[str]:
        """What is missing from the guard of a running network (WD-7)."""
        interface = self._guarded.get(net_id)
        if interface is None:
            return []
        found = []
        for family, run in (("IPv4", execute_iptables), ("IPv6", _ip6tables)):
            try:
                run(["-C", *_jump(interface, net_id)])
            except CommandError:
                found.append(f"{family} host guard")
        return found

    def has(self, net_id: str) -> bool:
        return net_id in self._guarded

    @staticmethod
    def remove_stale() -> None:
        """Delete every Wi-Lab guard jump and chain left by a previous run. Never raises."""
        for run in (execute_iptables, _ip6tables):
            try:
                for line in run(["-S", "INPUT"]).splitlines():
                    tokens = shlex.split(line)
                    comments = [v for option, v in pairwise(tokens) if option == "--comment"]
                    if tokens[:2] == ["-A", "INPUT"] and any(c.startswith(JUMP_COMMENT_PREFIX) for c in comments):
                        run(["-D", *tokens[1:]])
                for line in run(["-S"]).splitlines():
                    tokens = shlex.split(line)
                    if tokens[:1] == ["-N"] and len(tokens) > 1 and tokens[1].startswith(CHAIN_PREFIX):
                        run(["-F", tokens[1]])
                        run(["-X", tokens[1]])
            except (CommandError, ValueError) as exc:
                logger.error("Could not remove stale host guard rules: %s", exc)


def remove_stale_guards() -> None:
    """Startup hook: remove host guards left by a previous run."""
    HostGuard.remove_stale()
