"""HAP-8: the last hostapd output lines reach the journal when hostapd fails or dies, without secrets."""

import logging
import subprocess
import sys

from wilab.network.commands import start_foreground
from wilab.wifi import hostapd

SCRIPT = (
    "import sys\n"
    "for i in range(100): print(f'line {i}')\n"
    "print('WPA: PSK - hexdump(len=32): 00 11 22')\n"
    "print('wpa_passphrase=secret-pass')\n"
    "print('nl80211: kernel reports: Match already configured')\n"
    "sys.stdout.flush()\n"
)


def _child():
    process = start_foreground(
        [sys.executable, "-c", SCRIPT], classify_output=lambda _line: None, keep_lines=hostapd.LOG_TAIL_LINES,
    )
    for _ in range(100):
        if process.poll() is not None:
            break
        subprocess.run(["sleep", "0.02"], check=False)
    return process


def test_the_tail_is_logged_without_secret_lines(caplog):
    process = _child()
    with caplog.at_level(logging.WARNING):
        hostapd.log_tail("wlan0", "died on an active network", process)
    text = caplog.text
    assert "Match already configured" in text
    assert "PSK" not in text and "secret-pass" not in text
    logged = [line for line in text.splitlines() if line.startswith("line ")]
    assert len(logged) <= hostapd.LOGGED_TAIL_LINES


def test_report_exit_logs_only_a_dead_hostapd(caplog):
    process = _child()
    manager = hostapd.HostapdManager()
    manager._instances["wlan0"] = {
        "interface": "wlan0", "config_file": "/nonexistent", "control_dir": "/nonexistent",
        "ssid": "x", "process": process,
    }
    with caplog.at_level(logging.WARNING):
        manager.report_exit("wlan0")
    assert "died on an active network" in caplog.text


def test_a_broken_process_object_never_breaks_a_start(caplog):
    hostapd.log_tail("wlan0", "failed to start", object())   # no output_tail: ignored
