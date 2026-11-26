"""Captive portal on the real service (e2e-test-10).

The portal page is served on the gateway at `captive_portal_port` (8081 by
default, which this test expects); the nat chain `wilab-cp-<if>` sends the
clients' HTTP (port 80) there, and the host guard `wilab-in-<if>` accepts the
portal port but never the API port. Whether a real client can open the API is
the phone test in Fable-Notes.md, 5.4; here the rules are read with
`iptables -S` (root) and the page is fetched from the host itself.
"""

from concurrent.futures import ThreadPoolExecutor

import httpx
from wilab_e2e import Antenna, Server, WiLab

PORTAL_PORT = 8081
API_PORT = 8080
RADIOS = [("2.4ghz", 6), ("5ghz", 36)]


def _check_portal(wilab: WiLab, server: Server, antenna: Antenna) -> str:
    """Assert the portal of one network is in place; return its gateway."""
    network = wilab.network(antenna).json()
    gateway = network["ip"]["gateway"]
    assert network["captive_portal"]["enabled"] is True, network
    url = network["captive_portal"]["url"]
    assert url == f"http://{gateway}:{PORTAL_PORT}/", url

    redirect = server.chain_rules(f"wilab-cp-{antenna.interface}", table="nat")
    http = [line for line in redirect if "-p tcp" in line and "--dport 80 " in line]
    assert any(line.endswith(f"-j DNAT --to-destination {gateway}:{PORTAL_PORT}") for line in http), redirect
    assert not any(str(API_PORT) in line for line in redirect), redirect

    guard_chain = f"wilab-in-{antenna.interface}"
    guard = server.chain_rules(guard_chain)
    accepted = [line for line in guard if line.endswith("-j ACCEPT")]
    assert any(f"--dport {PORTAL_PORT}" in line for line in accepted), guard
    assert not any(f"--dport {API_PORT}" in line for line in accepted), guard
    assert guard[-1].startswith(f"-A {guard_chain} -j REJECT"), guard

    assert f"{gateway}:{PORTAL_PORT}" in server.listening_tcp()
    page = httpx.get(url, timeout=5, trust_env=False)
    assert page.status_code == 200 and "WiLab Captive Portal" in page.text, page.text[:200]
    return gateway


def test_portals_on_every_antenna_start_together(wilab: WiLab, server: Server) -> None:
    """e2e-test-10: one portal per antenna, created at the same time, each on its own gateway:8081.

    With one antenna only the single-portal checks run.
    """
    antennas = [wilab.reserve(interface) for interface in wilab.interfaces()]

    def create(index: int) -> int:
        band, channel = RADIOS[index % len(RADIOS)]
        response = wilab.create(
            antennas[index], ssid=f"wilab-e2e-portal-{index}", band=band, channel=channel, captive_portal=True,
        )
        return response.status_code

    with ThreadPoolExecutor(len(antennas)) as pool:
        codes = list(pool.map(create, range(len(antennas))))
    assert codes == [200] * len(antennas), codes

    gateways = [_check_portal(wilab, server, antenna) for antenna in antennas]
    assert len(set(gateways)) == len(gateways), gateways

    for antenna, gateway in zip(antennas, gateways, strict=True):
        assert wilab.delete_network(antenna) == 200
        assert server.chain_rules(f"wilab-cp-{antenna.interface}", table="nat") == []
        assert f"{gateway}:{PORTAL_PORT}" not in server.listening_tcp()
