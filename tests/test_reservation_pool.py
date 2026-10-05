"""Allocation behaviour on a realistic pool of ten antennas, with many reservations at once.

The pool mixes the three kinds of adapter a lab has - 2.4 GHz only, 5 GHz only and dual band -
interleaved on purpose, so declaration order and capability pull in different directions.

Rule under test: a request gets the free device with the FEWEST capabilities beyond those it
asked for (ties go to the first declared), so adapters offering more than was requested are
used last. A request no device could ever satisfy is an error; one that only has to wait is
a different error.
"""

import random
import threading
from typing import Dict, FrozenSet, List, Optional, Set

import pytest

from wilab.config import Capability
from wilab.reservation import (
    CapabilityUnsatisfiableError,
    DeviceSpec,
    NoDeviceAvailableError,
    ReservationManager,
)

C24, C5 = Capability.BAND_24GHZ, Capability.BAND_5GHZ
ONLY24, ONLY5, DUAL = frozenset({C24}), frozenset({C5}), frozenset({C24, C5})

# index:    0     1       2      3     4       5      6     7       8      9
LAYOUT = [DUAL, ONLY24, ONLY5, DUAL, ONLY24, ONLY5, DUAL, ONLY24, ONLY5, DUAL]
NAMES = [f"d{i}" for i in range(len(LAYOUT))]
KIND = {n: caps for n, caps in zip(NAMES, LAYOUT)}

DUALS = [n for n in NAMES if KIND[n] == DUAL]      # d0 d3 d6 d9
ONLY24S = [n for n in NAMES if KIND[n] == ONLY24]  # d1 d4 d7
ONLY5S = [n for n in NAMES if KIND[n] == ONLY5]    # d2 d5 d8


@pytest.fixture
def pool() -> ReservationManager:
    return ReservationManager(
        [DeviceSpec(device_id=n, capabilities=caps, index=i)
         for i, (n, caps) in enumerate(zip(NAMES, LAYOUT))]
    )


def take(mgr: ReservationManager, *caps: Capability, seconds: int = 3600) -> str:
    return mgr.create(seconds, required_capabilities=set(caps)).device_id


class TestTightestFit:
    def test_5ghz_requests_use_the_5ghz_only_devices_before_any_dual_band(self, pool):
        got = [take(pool, C5) for _ in range(5)]
        assert got[:3] == ONLY5S                    # d2 d5 d8, declaration order
        assert got[3:] == DUALS[:2]                 # then dual band, declaration order

    def test_24ghz_requests_use_the_24ghz_only_devices_before_any_dual_band(self, pool):
        got = [take(pool, C24) for _ in range(5)]
        assert got[:3] == ONLY24S
        assert got[3:] == DUALS[:2]

    def test_a_dual_band_request_can_only_be_served_by_dual_band_devices(self, pool):
        assert [take(pool, C24, C5) for _ in range(4)] == DUALS

    def test_the_report_of_what_you_got_lists_every_capability_of_the_device(self, pool):
        for _ in range(3):
            take(pool, C5)                           # consume the 5 GHz-only devices
        reservation = pool.create(60, required_capabilities={C5})
        spec = next(d for d in pool._devices if d.device_id == reservation.device_id)
        assert spec.capabilities == DUAL             # asked 5 GHz, got a device with both

    def test_a_request_never_wastes_a_scarcer_device_when_a_tighter_one_is_free(self, pool):
        """With 24-only and 5-only free, neither request may touch a dual-band device."""
        a, b = take(pool, C24), take(pool, C5)
        assert KIND[a] == ONLY24 and KIND[b] == ONLY5


class TestDemandMixes:
    def test_the_whole_pool_can_be_booked_whatever_the_arrival_order(self, pool):
        """Four dual, three 2.4-only, three 5-only: ten requests of the right kinds all succeed."""
        demand = [(C24, C5)] * 4 + [(C5,)] * 3 + [(C24,)] * 3
        random.Random(7).shuffle(demand)
        got = [take(pool, *caps) for caps in demand]
        assert sorted(got) == sorted(NAMES)

    def test_dual_band_devices_survive_for_those_who_need_both_bands(self, pool):
        for _ in range(3):
            take(pool, C5)
            take(pool, C24)
        # six single-band requests served by the six single-band devices; all duals intact
        assert [take(pool, C24, C5) for _ in range(4)] == DUALS

    def test_demand_for_one_band_spills_over_to_dual_band_then_waits(self, pool):
        for _ in range(7):                           # 3 five-only + 4 dual
            take(pool, C5)
        with pytest.raises(NoDeviceAvailableError):
            take(pool, C5)
        # the 2.4-only devices were never touched and still serve 2.4 requests
        assert [take(pool, C24) for _ in range(3)] == ONLY24S

    def test_waiting_is_not_the_same_as_impossible(self, pool):
        for _ in range(4):
            take(pool, C24, C5)
        with pytest.raises(NoDeviceAvailableError):   # exists, all busy: retry later
            take(pool, C24, C5)

    def test_a_band_no_device_has_is_impossible_not_busy(self):
        only24_pool = ReservationManager(
            [DeviceSpec(device_id=f"x{i}", capabilities=ONLY24, index=i) for i in range(5)]
        )
        with pytest.raises(CapabilityUnsatisfiableError) as exc:
            take(only24_pool, C5)
        assert exc.value.available == ["2.4ghz"]


class TestReleaseAndReuse:
    def test_a_released_tight_device_is_preferred_again(self, pool):
        first = [pool.create(3600, required_capabilities={C5}) for _ in range(4)]
        assert KIND[first[3].device_id] == DUAL          # the 4th spilled onto a dual
        pool.delete(first[1].reservation_id)             # d5 (5-only) comes back
        assert take(pool, C5) == "d5"                    # not another dual-band device

    def test_releasing_a_dual_band_device_does_not_help_a_single_band_queue_jump(self, pool):
        held = [pool.create(3600, required_capabilities={C24, C5}) for _ in range(4)]
        pool.delete(held[2].reservation_id)
        assert take(pool, C24, C5) == held[2].device_id

    def test_eta_only_counts_devices_that_could_serve_the_request(self, pool):
        for name in ONLY24S:                              # 2.4-only devices, free very soon
            pool.create(30, required_capabilities={C24})
        for _ in range(7):                                # all 5 GHz capable devices, long hold
            pool.create(3600, required_capabilities={C5})
        with pytest.raises(NoDeviceAvailableError) as exc:
            take(pool, C5)
        assert exc.value.next_available_in is not None and exc.value.next_available_in > 60

    def test_unlimited_holders_give_no_eta(self, pool):
        for _ in range(7):
            pool.create(0, required_capabilities={C5})
        with pytest.raises(NoDeviceAvailableError) as exc:
            take(pool, C5)
        assert exc.value.next_available_at is None


class TestAgainstAReferenceModel:
    """Random create/release sequences, checked against a brute-force statement of the rule."""

    @staticmethod
    def expected(free: Set[str], required: FrozenSet[Capability]):
        fitting = [n for n in NAMES if n in free and required <= KIND[n]]
        if not fitting:
            return None
        return min(fitting, key=lambda n: (len(KIND[n] - required), NAMES.index(n)))

    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
    def test_every_decision_matches_the_rule(self, pool, seed):
        rng = random.Random(seed)
        requests = [frozenset({C24}), frozenset({C5}), frozenset({C24, C5})]
        free: Set[str] = set(NAMES)
        held: Dict[str, str] = {}                       # reservation_id -> device_id
        for _ in range(400):
            if held and rng.random() < 0.4:
                rid = rng.choice(sorted(held))
                assert pool.delete(rid)
                free.add(held.pop(rid))
                continue
            required = rng.choice(requests)
            want = self.expected(free, required)
            if want is None:
                with pytest.raises(NoDeviceAvailableError):
                    pool.create(3600, required_capabilities=required)
            else:
                reservation = pool.create(3600, required_capabilities=required)
                assert reservation.device_id == want
                free.discard(want)
                held[reservation.reservation_id] = want
        # no device is ever held twice
        assert len(set(held.values())) == len(held)


class TestSimultaneousReservations:
    def run_threads(self, pool: ReservationManager, wanted: List[FrozenSet[Capability]]):
        results: List[tuple] = []  # (required, status, device)
        lock = threading.Lock()
        barrier = threading.Barrier(len(wanted))

        def worker(required: FrozenSet[Capability]) -> None:
            barrier.wait()                              # start together
            status: str
            device: Optional[str]
            try:
                device = pool.create(3600, required_capabilities=required).device_id
                status = "ok"
            except NoDeviceAvailableError:
                device, status = None, "busy"
            with lock:
                results.append((required, status, device))

        threads = [threading.Thread(target=worker, args=(r,)) for r in wanted]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_twenty_clients_for_5ghz_get_exactly_the_seven_capable_devices(self, pool):
        results = self.run_threads(pool, [frozenset({C5})] * 20)
        granted = [dev for _, status, dev in results if status == "ok"]
        assert len(granted) == 7 and len(set(granted)) == 7
        assert set(granted) == set(ONLY5S + DUALS)
        assert sum(1 for _, status, _ in results if status == "busy") == 13

    def test_a_mixed_crowd_never_double_books_and_always_respects_the_request(self, pool):
        wanted = [frozenset({C24})] * 10 + [frozenset({C5})] * 10 + [frozenset({C24, C5})] * 10
        results = self.run_threads(pool, wanted)
        granted = [(req, dev) for req, status, dev in results if status == "ok"]
        devices = [dev for _, dev in granted]
        assert len(devices) == len(set(devices))                  # nobody got a taken device
        assert all(req <= KIND[dev] for req, dev in granted)      # every grant fits its request
        assert 0 < len(granted) <= len(NAMES)

    def test_when_demand_matches_supply_everybody_is_served_by_their_own_class(self, pool):
        """4 dual-band, 3 five-only and 3 two-point-four-only clients arrive at the same instant.

        Each single-band group is exactly as large as its tight class, so a tighter device is
        always still free for it: nobody spills onto a dual-band device and nobody is refused,
        whatever the arrival order.
        """
        wanted = [frozenset({C24, C5})] * 4 + [frozenset({C5})] * 3 + [frozenset({C24})] * 3
        results = self.run_threads(pool, wanted)
        assert all(status == "ok" for _, status, _ in results)
        by_request: Dict[FrozenSet[Capability], Set[Optional[str]]] = {}
        for req, _, dev in results:
            by_request.setdefault(req, set()).add(dev)
        assert by_request[frozenset({C5})] == set(ONLY5S)
        assert by_request[frozenset({C24})] == set(ONLY24S)
        assert by_request[frozenset({C24, C5})] == set(DUALS)
