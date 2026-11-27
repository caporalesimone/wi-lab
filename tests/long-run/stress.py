"""Building blocks of the long-run stress tests: time budget, event log, random networks, workers."""

from __future__ import annotations

import json
import os
import random
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from wilab_e2e import Antenna, Server, WiLab, detail_code, gone_reason

RESULTS = Path(__file__).resolve().parent / "results"

# Share of WILAB_LONG_MINUTES given to each test; they add up to 1 (two hours by default).
WEIGHTS = {"sequential": 0.25, "parallel": 0.30, "chaos": 0.20, "hold": 0.25}

START_TIMEOUT = 360        # a start never takes longer (DFS excluded; the server retries inside)
RECOVERY_WAIT = 20 * 60    # an antenna in quarantine comes back within about 11-15 minutes


def budget(name: str) -> float:
    """Seconds this test may run."""
    return float(os.environ.get("WILAB_LONG_MINUTES", "120")) * 60 * WEIGHTS[name]


class Recorder:
    """Thread-safe log of what happened: JSON lines on disk, counters, unexpected answers."""

    def __init__(self, name: str) -> None:
        RESULTS.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S")
        self.path = RESULTS / f"{stamp}-{name}.jsonl"
        self.name = name
        self.counts: Counter[str] = Counter()
        self.failures: list[str] = []
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self._file = self.path.open("a", encoding="utf-8")

    def event(self, kind: str, **data: Any) -> None:
        with self._lock:
            self.counts[kind] += 1
            line = {"t": round(time.monotonic() - self.started, 1), "kind": kind, **data}
            self._file.write(json.dumps(line, default=str) + "\n")
            self._file.flush()

    def fail(self, what: str, **data: Any) -> None:
        self.event("FAILURE", what=what, **data)
        with self._lock:
            self.failures.append(f"{what} {data}")

    def summary(self) -> str:
        minutes = (time.monotonic() - self.started) / 60
        counts = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
        return f"[{self.name}] {minutes:.1f} min; {counts}; failures={len(self.failures)}; log {self.path}"

    def close(self) -> None:
        self._file.close()


def random_settings(rng: random.Random, details: dict[str, Any]) -> dict[str, Any]:
    """A create body the antenna says it supports (GET /antennas/{interface}), DFS excluded."""
    band = rng.choice(sorted(details["bands"]))
    options = details["bands"][band]
    encryption = rng.choice(details["encryptions"])
    generations = [g for g in options["wifi_generations"] if g["channel_widths"]]
    if encryption == "wpa1":       # WPA1 is 802.11g/n only, 20 MHz
        generations = [g for g in generations if g["wifi_generation"] == 4]
    generation = rng.choice(generations)
    widths = [20] if encryption == "wpa1" else generation["channel_widths"]
    width = rng.choice(widths)
    channels = [c["channel"] for c in options["channels"] if not c.get("dfs") and width in c["channel_widths"]]
    if not channels:
        width, channels = 20, [c["channel"] for c in options["channels"] if not c.get("dfs")]
    ssid = rng.choice(["stress", "Caffè ☕", 'my"net\\', "x" * 32, "lr-" + str(rng.randint(0, 9999))])
    body: dict[str, Any] = {
        "ssid": ssid, "band": band, "channel": rng.choice(channels), "channel_width": width,
        "wifi_generation": generation["wifi_generation"], "encryption": encryption,
        "tx_power_level": rng.randint(1, 4), "hidden": rng.random() < 0.2,
        "internet_enabled": rng.random() < 0.7, "captive_portal": rng.random() < 0.2,
        "password": None,
    }
    if encryption != "open":
        length = rng.choice([8, 12, 32, 63])
        body["password"] = "".join(rng.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(length))
    return body


def wait_reserve(client: WiLab, interface: str, rec: Recorder, duration: int = 4 * 3600) -> Antenna:
    """Reserve *interface*, waiting while it is held or recovering (after a quarantine)."""
    deadline = time.monotonic() + RECOVERY_WAIT
    while True:
        response = client.http.post("/reservations", json={"duration_seconds": duration, "interface": interface})
        if response.status_code == 200:
            data = response.json()
            client.reserved.append(data["reservation_id"])
            return Antenna(data["reservation_id"], data["interface"], data["display_name"])
        rec.event("reserve_wait", interface=interface, status=response.status_code, code=detail_code(response))
        if response.status_code not in (409, 503) or time.monotonic() > deadline:
            rec.fail("reserve", interface=interface, status=response.status_code, body=response.text[:300])
            raise RuntimeError(f"cannot reserve {interface}: {response.status_code}")
        time.sleep(15)


def stop_network(client: WiLab, antenna: Antenna, rec: Recorder) -> None:
    """DELETE .../network until it answers 200 or 409 / 1007 (both: stopped)."""
    for _ in range(30):
        response = client.http.delete(f"/reservations/{antenna.reservation_id}/network")
        code = detail_code(response)
        if response.status_code == 200 or (response.status_code == 409 and code == 1007):
            return
        if response.status_code == 503 and code in (1006, 1012):
            rec.event("stop_retry", interface=antenna.interface, code=code)
            time.sleep(int(response.headers.get("Retry-After", "2")))
            continue
        if response.status_code == 404:
            rec.event("stop_on_gone", interface=antenna.interface, reason=gone_reason(response))
            return
        rec.fail("stop", interface=antenna.interface, status=response.status_code, body=response.text[:300])
        return
    rec.fail("stop_never_completed", interface=antenna.interface)


def create(client: WiLab, antenna: Antenna, body: dict[str, Any], rec: Recorder) -> str:
    """One create to its end. Returns "up", "failed" (start_failed or unexpected) or "lost" (404)."""
    began = time.monotonic()
    posted = client.post_network(antenna, **body)
    if posted.status_code == 503 and detail_code(posted) == 1006:
        time.sleep(2)
        posted = client.post_network(antenna, **body)
    if posted.status_code == 404:
        rec.event("lost", interface=antenna.interface, reason=gone_reason(posted))
        return "lost"
    if posted.status_code not in (200, 202):
        rec.fail("create_refused", interface=antenna.interface, status=posted.status_code,
                 body=posted.text[:300], request={k: v for k, v in body.items() if k != "password"})
        return "failed"
    try:
        final = client.wait_start(antenna, timeout=START_TIMEOUT) if posted.status_code == 202 else posted
    except TimeoutError:
        rec.fail("start_never_ended", interface=antenna.interface)
        return "failed"
    seconds = round(time.monotonic() - began, 1)
    if final.status_code == 404:
        rec.event("lost", interface=antenna.interface, reason=gone_reason(final), seconds=seconds)
        return "lost"
    state = final.json()
    if state.get("active") is True:
        rec.event("up", interface=antenna.interface, seconds=seconds, band=body["band"],
                  channel=body["channel"], width=body["channel_width"], encryption=body["encryption"])
        if state["wifi"]["ssid"] != body["ssid"]:
            rec.fail("wrong_ssid", interface=antenna.interface, got=state["wifi"]["ssid"])
        return "up"
    if state.get("runtime_state") == "start_failed":
        rec.fail("start_failed", interface=antenna.interface, error=state.get("error"),
                 request={k: v for k, v in body.items() if k != "password"})
        return "failed"
    rec.fail("start_ended_without_network", interface=antenna.interface, state=state)
    return "failed"


def exercise(client: WiLab, antenna: Antenna, rng: random.Random, rec: Recorder, seconds: float) -> None:
    """Use a running network for a while: reads and Internet toggles, all must answer 200."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        action = rng.choice(["get", "get", "internet_off", "internet_on", "status"])
        if action == "get":
            response = client.network(antenna)
        elif action == "status":
            response = client.http.get("/status")
        else:
            verb = "disable" if action == "internet_off" else "enable"
            response = client.http.post(f"/reservations/{antenna.reservation_id}/internet/{verb}")
        if response.status_code == 503 and detail_code(response) == 1006:
            rec.event("busy", interface=antenna.interface, action=action)
        elif response.status_code != 200:
            rec.fail("exercise", interface=antenna.interface, action=action, status=response.status_code,
                     body=response.text[:300])
        time.sleep(rng.uniform(0.5, 3))


def churn(client: WiLab, interface: str, rng: random.Random, rec: Recorder, until: float,
          stop: threading.Event | None = None) -> None:
    """Create, use and stop networks with random settings on *interface* until *until*."""
    details = client.antenna(interface)
    antenna = wait_reserve(client, interface, rec)
    while time.monotonic() < until and not (stop and stop.is_set()):
        body = random_settings(rng, details)
        outcome = create(client, antenna, body, rec)
        if outcome == "lost":
            antenna = wait_reserve(client, interface, rec)
            continue
        if outcome == "up":
            exercise(client, antenna, rng, rec, rng.uniform(1, 20))
        stop_network(client, antenna, rec)
    client.release(antenna)


def in_threads(*targets: Callable[[], None]) -> list[BaseException]:
    """Run the targets in parallel; the exceptions they raised."""
    errors: list[BaseException] = []

    def run(target: Callable[[], None]) -> None:
        try:
            target()
        except BaseException as exc:  # noqa: BLE001 - reported by the test
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(t,), daemon=True) for t in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def assert_clean(client: WiLab, server: Server, rec: Recorder, interfaces: list[str]) -> None:
    """After a test: no reservation, no network, no process, no rule, no antenna in recovery."""
    deadline = time.monotonic() + RECOVERY_WAIT
    while True:
        status = client.status()
        recovering = [a["display_name"] for a in status["antennas"] if a.get("recovery_state")]
        if not recovering or time.monotonic() > deadline:
            break
        rec.event("waiting_recovery", antennas=recovering)
        time.sleep(30)
    problems = []
    if recovering:
        problems.append(f"antennas still in recovery: {recovering}")
    if status["status"] == "degraded":
        problems.append(f"status degraded: {status.get('degraded_reasons')}")
    if status["active_networks"]:
        problems.append(f"active networks: {status['active_networks']}")
    if server.pids("hostapd"):
        problems.append(f"hostapd left: {server.pids('hostapd')}")
    for interface in interfaces:
        if server.dnsmasq_pids(interface):
            problems.append(f"dnsmasq left on {interface}")
        rules = server.wilab_rules(interface)
        if rules:
            problems.append(f"rules left on {interface}: {rules[:5]}")
    for problem in problems:
        rec.fail("not_clean", problem=problem)


def seed() -> int:
    return int(os.environ.get("WILAB_LONG_SEED", str(int(time.time()))))


def stop_or_gone(response: httpx.Response) -> bool:
    return response.status_code == 200 or (response.status_code == 409 and detail_code(response) == 1007)
