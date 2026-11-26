"""The shared test tools behave as the tests that use them expect."""

import pytest
from helpers import CommandRecorder, FakeClock

from wilab.network.commands import CommandError


def test_fake_clock_moves_both_clocks_or_only_the_wall_clock():
    clock = FakeClock()
    clock.advance(10)
    assert (clock.monotonic(), clock.time()) == (1010.0, 1_800_000_010.0)
    clock.jump_wall_clock(7200)
    assert clock.monotonic() == 1010.0
    clock.sleep(5)
    assert clock.monotonic() == 1015.0


def test_command_recorder_answers_records_and_fails_a_limited_number_of_times():
    run = CommandRecorder()
    run.outputs[("iw", "dev")] = "Interface wlan0"
    run.fail(("iptables",), CommandError("xtables lock"), times=1)
    assert run(["iw", "dev"]) == "Interface wlan0"
    with pytest.raises(CommandError):
        run(["iptables", "-S"])
    assert run(["iptables", "-S"]) == ""   # failed only once
    assert run.ran("iptables") == [["iptables", "-S"], ["iptables", "-S"]]
