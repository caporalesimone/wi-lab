"""ARCH-2: one failure classification, set where the error is born."""

import pytest

from wilab.api.routes.network import _ON_START_FAILURE
from wilab.wifi import hostapd
from wilab.wifi.failures import FailureKind
from wilab.wifi.manager import StartupFailure
from wilab.wifi.watchdog import _ON_RESTORE_FAILURE


def _hostapd_exceptions() -> list[type[hostapd.HostapdError]]:
    found, todo = [], [hostapd.HostapdError]
    while todo:
        cls = todo.pop()
        found.append(cls)
        todo.extend(cls.__subclasses__())
    return found


@pytest.mark.parametrize("cls", _hostapd_exceptions(), ids=lambda cls: cls.__name__)
def test_every_hostapd_exception_has_a_kind(cls) -> None:
    assert isinstance(cls.kind, FailureKind)


def test_radio_failures_are_transient_radio() -> None:
    for cls in (hostapd.HostapdRadioFailure, hostapd.HostapdSegfault, hostapd.HostapdInitFailure):
        assert cls.kind is FailureKind.TRANSIENT_RADIO
    assert hostapd.HostapdError.kind is FailureKind.CONFIGURATION


def test_create_job_table_covers_every_kind() -> None:
    assert set(_ON_START_FAILURE) == set(FailureKind)


def test_watchdog_table_covers_every_kind() -> None:
    assert set(_ON_RESTORE_FAILURE) == set(FailureKind)


@pytest.mark.parametrize("kind", list(FailureKind), ids=lambda kind: kind.name)
def test_startup_failure_flags_derive_from_kind(kind) -> None:
    failure = StartupFailure("x", kind=kind)
    assert failure.radio == (kind in (FailureKind.TRANSIENT_RADIO, FailureKind.RADIO_CLEANUP_FAILED))
    assert failure.cleanup_failed == (kind in (FailureKind.CLEANUP_FAILED, FailureKind.RADIO_CLEANUP_FAILED))
