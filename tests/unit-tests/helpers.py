"""Shared test tools (Fable chapter 4.1): a fake clock and a command recorder."""

from collections.abc import Iterable


class FakeClock:
    """Replaces time.monotonic, time.time and time.sleep in the modules under test.

    Hours pass in microseconds: `advance` moves both clocks, `jump_wall_clock`
    moves only the wall clock, like an NTP step (STAB-5).
    """

    def __init__(self) -> None:
        self.monotonic_now = 1000.0
        self.wall_now = 1_800_000_000.0

    def monotonic(self) -> float:
        return self.monotonic_now

    def time(self) -> float:
        return self.wall_now

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.monotonic_now += seconds
        self.wall_now += seconds

    def jump_wall_clock(self, seconds: float) -> None:
        self.wall_now += seconds

    def install(self, monkeypatch, *modules) -> "FakeClock":
        """Point `time.monotonic`, `time.time` and `time.sleep` of *modules* here.

        The modules share the one `time` module object, so this patches it for
        the whole test (monkeypatch restores it afterwards).
        """
        for module in modules:
            monkeypatch.setattr(module.time, "monotonic", self.monotonic)
            monkeypatch.setattr(module.time, "time", self.time)
            monkeypatch.setattr(module.time, "sleep", self.sleep)
        return self


class CommandRecorder:
    """A stand-in for execute_command: records every call and answers from tables.

    `failures` and `outputs` map a command prefix (a tuple of the first
    arguments) to the error to raise or the output to return. A failure can be
    limited to its first `n` matches with `fail(prefix, error, times=n)`.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.failures: dict[tuple[str, ...], Exception] = {}
        self.outputs: dict[tuple[str, ...], str] = {}
        self._remaining: dict[tuple[str, ...], int] = {}

    def fail(self, prefix: Iterable[str], error: Exception, *, times: int | None = None) -> None:
        key = tuple(prefix)
        self.failures[key] = error
        if times is not None:
            self._remaining[key] = times

    def __call__(self, cmd: list[str], *args: object, **kwargs: object) -> str:
        self.calls.append(list(cmd))
        for prefix, error in list(self.failures.items()):
            if tuple(cmd[: len(prefix)]) == prefix:
                if prefix in self._remaining:
                    self._remaining[prefix] -= 1
                    if self._remaining[prefix] <= 0:
                        del self.failures[prefix]
                        del self._remaining[prefix]
                raise error
        for prefix, output in self.outputs.items():
            if tuple(cmd[: len(prefix)]) == prefix:
                return output
        return ""

    def ran(self, *prefix: str) -> list[list[str]]:
        """The recorded calls that start with *prefix*."""
        return [call for call in self.calls if tuple(call[: len(prefix)]) == prefix]
