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
WEIGHTS = {"sequential": 0.15, "parallel": 0.20, "chaos": 0.15, "hold": 0.15, "burst": 0.35}

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
    """A create body the antenna says it supports (GET /antennas/{interface}/capabilities), DFS excluded."""
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
    details = client.capabilities(interface)
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
    if status["service"]["health"] == "degraded":
        problems.append(f"status degraded: {status["service"]["degraded_reasons"]}")
    running = [a["interface"] for a in status["antennas"] if a["network_active"]]
    if running:
        problems.append(f"active networks: {running}")
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


# --------------------------------------------------------------------------- burst and fault injection

# Faults the chaos monkey injects per antenna and rolling hour: below the watchdog
# budgets (3 AP restores, 3 DHCP restarts), so a quarantine is never its doing.
MONKEY_AP_KILLS_PER_HOUR = 2
MONKEY_DHCP_KILLS_PER_HOUR = 2
RESTORE_LIMIT_S = 45       # a killed hostapd or dnsmasq is back within this time


class Targets:
    """Networks that dwell (up, nobody touching them) and may be hit by the monkey."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dwelling: dict[str, tuple[WiLab, Antenna]] = {}
        self._busy: dict[str, threading.Event] = {}

    def offer(self, client: WiLab, antenna: Antenna) -> None:
        with self._lock:
            self._dwelling[antenna.interface] = (client, antenna)

    def withdraw(self, interface: str) -> None:
        """The worker wants its network back: wait until the monkey is done with it."""
        with self._lock:
            self._dwelling.pop(interface, None)
            busy = self._busy.get(interface)
        if busy is not None:
            busy.wait(RESTORE_LIMIT_S + 30)

    def take(self, rng: random.Random, allowed: Callable[[str], bool]) -> tuple[WiLab, Antenna, threading.Event] | None:
        with self._lock:
            choices = [i for i in self._dwelling if allowed(i)]
            if not choices:
                return None
            interface = rng.choice(choices)
            client, antenna = self._dwelling.pop(interface)
            done = threading.Event()
            self._busy[interface] = done
            return client, antenna, done

    def give_back(self, interface: str, done: threading.Event) -> None:
        with self._lock:
            self._busy.pop(interface, None)
        done.set()


def _restarts(client: WiLab, antenna: Antenna) -> dict[str, Any] | None:
    response = client.network(antenna)
    return response.json() if response.status_code == 200 else None


def chaos_monkey(server: Server, targets: Targets, rng: random.Random, rec: Recorder, stop: threading.Event) -> None:
    """Kill hostapd (SIGSEGV) or dnsmasq (SIGKILL) of dwelling networks; check each comes back."""
    kills: dict[tuple[str, str], list[float]] = {}

    def recent(interface: str, kind: str) -> int:
        now = time.monotonic()
        times = kills.setdefault((interface, kind), [])
        times[:] = [t for t in times if now - t < 3600]
        return len(times)

    while not stop.wait(rng.uniform(10, 30)):
        kind = "ap" if rng.random() < 0.7 else "dhcp"
        limit = MONKEY_AP_KILLS_PER_HOUR if kind == "ap" else MONKEY_DHCP_KILLS_PER_HOUR
        def allowed(interface: str, kind: str = kind, limit: int = limit) -> bool:
            return recent(interface, kind) < limit

        taken = targets.take(rng, allowed)
        if taken is None:
            continue
        client, antenna, done = taken
        try:
            _strike(server, client, antenna, kind, rec)
            kills[(antenna.interface, kind)].append(time.monotonic())
        except Exception as exc:  # noqa: BLE001 - recorded, the run goes on
            rec.fail("monkey_error", interface=antenna.interface, fault=kind, error=repr(exc))
        finally:
            targets.give_back(antenna.interface, done)


def _strike(server: Server, client: WiLab, antenna: Antenna, kind: str, rec: Recorder) -> None:
    before = _restarts(client, antenna)
    if before is None or not before.get("active") or before.get("runtime_state"):
        return   # not a healthy dwelling network after all
    if kind == "ap":
        pid = server.hostapd_pid(antenna.interface)
        signal = "SEGV"
    else:
        pids = server.dnsmasq_pids(antenna.interface)
        pid, signal = (pids[0] if pids else None), "KILL"
    if pid is None:
        rec.fail("monkey_no_process", interface=antenna.interface, fault=kind)
        return
    struck = time.monotonic()
    server.kill(pid, signal)
    rec.event("monkey_kill", interface=antenna.interface, fault=kind, pid=pid, signal=signal)
    deadline = struck + RESTORE_LIMIT_S
    while time.monotonic() < deadline:
        state = _restarts(client, antenna)
        if (
            state is not None and state.get("active") and not state.get("runtime_state")
            and state["restarts"][kind] == before["restarts"][kind] + 1
        ):
            if kind == "ap":
                back = server.hostapd_pid(antenna.interface)
            else:
                dnsmasq = server.dnsmasq_pids(antenna.interface)
                back = dnsmasq[0] if dnsmasq else None
            if back is not None and back != pid:
                rec.event("monkey_recovered", interface=antenna.interface, fault=kind,
                          seconds=round(time.monotonic() - struck, 1),
                          reason=state["restarts"]["last_reason"])
                return
        time.sleep(0.5)
    rec.fail("monkey_not_recovered", interface=antenna.interface, fault=kind,
             state=_restarts(client, antenna), seconds=RESTORE_LIMIT_S)


def burst(client: WiLab, interface: str, rng: random.Random, rec: Recorder, until: float, targets: Targets) -> None:
    """Reserve, run 10-40 networks back to back with random settings and actions, release; again."""
    details = client.capabilities(interface)
    while time.monotonic() < until:
        antenna = wait_reserve(client, interface, rec, duration=rng.choice([600, 1800, 3600, 0]))
        count = rng.randint(10, 40)
        rec.event("burst_begin", interface=interface, networks=count, reservation=antenna.reservation_id)
        running = False
        for _ in range(count):
            if time.monotonic() >= until:
                break
            body = random_settings(rng, details)
            if running:   # left up by "keep": another body is refused, then it is stopped
                refused = client.post_network(antenna, **dict(body, ssid="burst-kept-" + str(rng.randint(0, 999))))
                if not (refused.status_code == 409 and detail_code(refused) == 1008):
                    rec.fail("burst_kept_conflict", interface=interface, status=refused.status_code,
                             code=detail_code(refused))
                stop_network(client, antenna, rec)
                running = False
            action = rng.choices(["plain", "cancel", "conflict", "dwell", "keep"], weights=[50, 15, 10, 15, 10])[0]
            if action == "cancel":
                posted = client.post_network(antenna, **body)
                time.sleep(rng.uniform(0, 2.5))
                stop_network(client, antenna, rec)
                after = client.network(antenna)
                if posted.status_code == 202 and after.status_code == 200 and after.json().get("active"):
                    rec.fail("cancel_left_network", interface=interface)
                rec.event("burst_cancel", interface=interface)
                continue
            outcome = create(client, antenna, body, rec)
            if outcome == "lost":
                antenna = wait_reserve(client, interface, rec)
                running = False
                continue
            running = outcome == "up"
            if running and action == "conflict":
                other = dict(body, ssid="burst-other-" + str(rng.randint(0, 999)))
                refused = client.post_network(antenna, **other)
                if not (refused.status_code == 409 and detail_code(refused) == 1008):
                    rec.fail("burst_conflict", interface=interface, status=refused.status_code,
                             code=detail_code(refused))
            elif running and action == "dwell":
                targets.offer(client, antenna)
                time.sleep(rng.uniform(20, 40))
                targets.withdraw(interface)
            elif running and action == "keep":
                continue   # no stop: the next create must refuse (other body) or the release cleans up
            stop_network(client, antenna, rec)
            running = False
        # A network left up is stopped half of the time; otherwise the release cleans it up.
        if running and rng.random() < 0.5:
            stop_network(client, antenna, rec)
            running = False
        rec.event("burst_release", interface=interface, network_running=running)
        client.release(antenna)
