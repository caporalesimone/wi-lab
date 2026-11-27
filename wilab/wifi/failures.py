"""What a failed network start is, decided once where the error is born (ARCH-2).

hostapd exceptions carry a class attribute ``kind``; ``StartupFailure`` gets its
kind once in ``NetworkManager._start_network`` from the cause and the rollback.
Callers never recompute it: the create job (``api/routes/network.py``,
``_ON_START_FAILURE``) and the watchdog (``wifi/watchdog.py``,
``_ON_RESTORE_FAILURE``) each map a kind to an action with one table.

Cancellation is not a kind: it is the caller's state (a released reservation,
a stopped network), checked by the caller next to the table, because the same
error can arrive whether or not the start was cancelled meanwhile.
"""

from enum import Enum


class FailureKind(Enum):
    # The radio did not come up (timeout, segfault, beacon setup, adapter gone):
    # the same request may work on a new start. Retried, then the adapter is
    # quarantined as a radio fault (USB recovery when configured).
    TRANSIENT_RADIO = "transient_radio"
    # A stage failed without a radio symptom: the request cannot work as is.
    # Rolled back; the client sees start_failed (1013) with the stage.
    CONFIGURATION = "configuration"
    # Another network is already active on the adapter: refused, nothing started.
    CONFLICT = "conflict"
    # The rollback failed: processes or rules may still be up. The adapter is
    # isolated (quarantine) or handed to the canceller's cleanup; never retried.
    CLEANUP_FAILED = "cleanup_failed"
    # Like CLEANUP_FAILED after a radio failure (or with the adapter gone): the
    # quarantine counts as a radio fault, so USB recovery may reset the adapter.
    RADIO_CLEANUP_FAILED = "radio_cleanup_failed"

    @property
    def radio(self) -> bool:
        """The adapter is suspect: a quarantine schedules USB recovery."""
        return self in (FailureKind.TRANSIENT_RADIO, FailureKind.RADIO_CLEANUP_FAILED)

    @property
    def cleanup_failed(self) -> bool:
        """Resources of the failed start may still be up."""
        return self in (FailureKind.CLEANUP_FAILED, FailureKind.RADIO_CLEANUP_FAILED)
