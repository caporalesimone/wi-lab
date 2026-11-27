"""Two hours (WILAB_LONG_MINUTES) of networks created through the API, on every antenna.

Every test runs for its share of the time, then checks that nothing is left
behind. An unexpected answer is a failure; a start that ends the reservation
with 404 (radio fault, quarantine) is recorded and waited out, not a failure.
"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from stress import (
    Recorder,
    Targets,
    assert_clean,
    budget,
    burst,
    chaos_monkey,
    churn,
    create,
    exercise,
    in_threads,
    random_settings,
    seed,
    stop_network,
    stop_or_gone,
    wait_reserve,
)
from wilab_e2e import WiLab, detail_code


def _finish(rec: Recorder, errors: list[BaseException] | None = None) -> None:
    print("\n" + rec.summary())
    for failure in rec.failures[:30]:
        print("  FAILURE", failure)
    rec.close()
    assert not errors, errors
    assert not rec.failures, f"{len(rec.failures)} unexpected answers, see {rec.path}"


def test_sequential_churn(idle: WiLab, server, base_url, token):
    """One antenna at a time: create with random settings, use it, stop it."""
    rng = random.Random(seed())
    rec = Recorder("sequential")
    rec.event("seed", seed=rng.random())
    interfaces = idle.interfaces()
    until = time.monotonic() + budget("sequential")
    index = 0
    while time.monotonic() < until:
        slice_end = min(until, time.monotonic() + 300)    # five minutes per antenna, alternating
        churn(idle, interfaces[index % len(interfaces)], rng, rec, slice_end)
        index += 1
    assert_clean(idle, server, rec, interfaces)
    _finish(rec)


def test_parallel_churn(idle: WiLab, server, base_url, token):
    """Both antennas at once, each with its own client and random settings."""
    rec = Recorder("parallel")
    base = seed()
    interfaces = idle.interfaces()
    until = time.monotonic() + budget("parallel")
    clients = [WiLab(base_url, token) for _ in interfaces]
    try:
        errors = in_threads(*[
            (lambda c=c, i=i, n=n: churn(c, i, random.Random(base + n), rec, until))
            for n, (c, i) in enumerate(zip(clients, interfaces))
        ])
    finally:
        for client in clients:
            client.close()
    assert_clean(idle, server, rec, interfaces)
    _finish(rec, errors)


def _chaos_round(client: WiLab, interface: str, rng: random.Random, rec: Recorder) -> None:
    details = client.antenna(interface)
    antenna = wait_reserve(client, interface, rec)
    action = rng.choice(["cancel", "release_while_starting", "same_body_again", "other_body", "reserve_churn", "storm"])
    rec.event("chaos", action=action, interface=interface)
    body = random_settings(rng, details)
    if action == "cancel":
        posted = client.post_network(antenna, **body)
        time.sleep(rng.uniform(0, 3))
        stop_network(client, antenna, rec)
        after = client.network(antenna)
        if posted.status_code == 202 and after.status_code == 200 and after.json().get("active"):
            rec.fail("cancel_left_network", interface=interface)
    elif action == "release_while_starting":
        client.post_network(antenna, **body)
        time.sleep(rng.uniform(0, 3))
        released = client.http.delete(f"/reservations/{antenna.reservation_id}")
        if released.status_code != 200:
            rec.fail("release_while_starting", interface=interface, status=released.status_code)
        antenna = wait_reserve(client, interface, rec)
    elif action == "same_body_again":
        first = client.post_network(antenna, **body)
        again = client.post_network(antenna, **body)
        if first.status_code == 202 and again.status_code not in (200, 202):
            rec.fail("same_body_again", interface=interface, status=again.status_code, code=detail_code(again))
        if create(client, antenna, body, rec) == "up":
            third = client.post_network(antenna, **body)
            if third.status_code != 200:
                rec.fail("same_body_on_running", interface=interface, status=third.status_code)
    elif action == "other_body" and create(client, antenna, body, rec) == "up":
        other = dict(body, ssid="other-" + str(rng.randint(0, 999)))
        refused = client.post_network(antenna, **other)
        if not (refused.status_code == 409 and detail_code(refused) == 1008):
            rec.fail("other_body", interface=interface, status=refused.status_code, code=detail_code(refused))
    elif action == "reserve_churn":
        for _ in range(3):
            client.release(antenna)
            antenna = wait_reserve(client, interface, rec)
    elif action == "storm" and create(client, antenna, body, rec) == "up":
        with ThreadPoolExecutor(max_workers=20) as pool:
            answers = list(pool.map(
                lambda n: (client.http.get("/status") if n % 2 else client.network(antenna)).status_code,
                range(40),
            ))
        if any(code not in (200, 503) for code in answers):
            rec.fail("storm", interface=interface, answers=sorted(set(answers)))
    stop_network(client, antenna, rec)
    client.release(antenna)


def test_chaos(idle: WiLab, server, base_url, token):
    """Cancels, releases during a start, repeated and conflicting creates, reserve churn, request storms."""
    rec = Recorder("chaos")
    base = seed()
    interfaces = idle.interfaces()
    until = time.monotonic() + budget("chaos")
    clients = [WiLab(base_url, token) for _ in interfaces]

    def loop(client: WiLab, interface: str, rng: random.Random) -> None:
        while time.monotonic() < until:
            _chaos_round(client, interface, rng, rec)

    try:
        errors = in_threads(*[
            (lambda c=c, i=i, n=n: loop(c, i, random.Random(base + 100 + n)))
            for n, (c, i) in enumerate(zip(clients, interfaces))
        ])
    finally:
        for client in clients:
            client.close()
    assert_clean(idle, server, rec, interfaces)
    _finish(rec, errors)


def test_hold_while_the_other_antenna_churns(idle: WiLab, server, base_url, token):
    """A network kept up for the whole time stays healthy while the other antenna churns."""
    rec = Recorder("hold")
    rng = random.Random(seed() + 200)
    holder, churner = idle.interfaces()[:2]
    until = time.monotonic() + budget("hold")
    hold_client, churn_client = WiLab(base_url, token), WiLab(base_url, token)

    def hold() -> None:
        antenna = wait_reserve(hold_client, holder, rec)
        body = {
            "ssid": "long-hold", "band": "5ghz", "channel": 36, "channel_width": 80, "wifi_generation": 5,
            "encryption": "wpa2", "password": "long-hold-pass", "tx_power_level": 4,
            "hidden": False, "internet_enabled": True, "captive_portal": False,
        }
        if create(hold_client, antenna, body, rec) != "up":
            rec.fail("hold_did_not_start", interface=holder)
            return
        restarts = hold_client.network(antenna).json()["restarts"]["ap"]
        while time.monotonic() < until:
            response = hold_client.network(antenna)
            if response.status_code != 200:
                rec.fail("hold_read", status=response.status_code, body=response.text[:300])
            else:
                state = response.json()
                if not state["active"] or state["runtime_state"] is not None:
                    rec.fail("hold_not_healthy", active=state["active"], runtime_state=state["runtime_state"])
                if state["restarts"]["ap"] != restarts:
                    rec.fail("hold_restarted", restarts=state["restarts"])
                    restarts = state["restarts"]["ap"]
                rec.event("hold_ok", clients=len(state.get("clients") or []))
            exercise(hold_client, antenna, rng, rec, 15)
        stopped = hold_client.http.delete(f"/reservations/{antenna.reservation_id}/network")
        if not stop_or_gone(stopped):
            rec.fail("hold_stop", status=stopped.status_code)
        hold_client.release(antenna)

    try:
        errors = in_threads(hold, lambda: churn(churn_client, churner, random.Random(rng.random()), rec, until))
    finally:
        hold_client.close()
        churn_client.close()
    assert_clean(idle, server, rec, [holder, churner])
    _finish(rec, errors)


def test_burst_on_every_antenna_with_fault_injection(idle: WiLab, server, base_url, token):
    """Every antenna in parallel: reserve, 10-40 random networks back to back, release, again.

    Random bands, channels, widths, generations, encryptions, SSIDs, hidden and
    captive portal; cancels during a start, conflicting creates, networks left
    up for the next create or for the release. Meanwhile a chaos monkey kills
    hostapd (SIGSEGV) or dnsmasq (SIGKILL) of networks that dwell, within the
    watchdog budgets, and each must come back by itself within 45 s with the
    `restarts` counter telling why. Afterwards nothing is left behind.
    """
    rec = Recorder("burst")
    base = seed()
    rec.event("seed", seed=base)
    interfaces = idle.interfaces()
    until = time.monotonic() + budget("burst")
    clients = [WiLab(base_url, token) for _ in interfaces]
    targets = Targets()
    stop = threading.Event()
    monkey = threading.Thread(
        target=chaos_monkey, args=(server, targets, random.Random(base + 400), rec, stop), daemon=True,
    )
    monkey.start()
    try:
        errors = in_threads(*[
            (lambda c=c, i=i, n=n: burst(c, i, random.Random(base + 300 + n), rec, until, targets))
            for n, (c, i) in enumerate(zip(clients, interfaces))
        ])
    finally:
        stop.set()
        monkey.join(120)
        for client in clients:
            client.close()
    assert_clean(idle, server, rec, interfaces)
    kills, recovered = rec.counts["monkey_kill"], rec.counts["monkey_recovered"]
    print(f"\nchaos monkey: {kills} kills, {recovered} recovered by themselves")
    _finish(rec, errors)
    assert kills >= 5, f"the monkey struck only {kills} times"
