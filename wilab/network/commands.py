import logging
import os
import subprocess
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock, Thread
from typing import Any, BinaryIO

logger = logging.getLogger(__name__)


class CommandError(Exception):
    """Exception raised when shell command execution fails.

    `returncode` is the exit code of a command that ran and failed; None when
    the command did not run or did not finish (not found, timeout, OSError).
    """

    def __init__(self, message: str = "", *, returncode: int | None = None) -> None:
        super().__init__(message)
        self.returncode = returncode


class CommandTimeout(CommandError):
    """The command did not finish before its deadline."""


class CommandStuck(CommandTimeout):
    """The child did not exit even after SIGKILL: it is stuck in the kernel (STAB-1)."""


# Seconds to wait for a killed child to exit. A child that outlives this is in an
# uninterruptible kernel call (a hung Wi-Fi driver holding the RTNL lock, for example):
# waiting for it would block the calling thread, and the device lock it holds, forever.
KILL_GRACE = 2.0

# Children that never exited after SIGKILL. Kept referenced so they can be reaped
# when they finally exit; their count is reported by GET /status.
_stuck_children: list[subprocess.Popen[Any]] = []
_stuck_lock = Lock()


def _remember_stuck(process: subprocess.Popen[Any], what: str) -> None:
    with _stuck_lock:
        _stuck_children.append(process)
    logger.critical(
        "%s (pid %d) did not exit after SIGKILL; it is stuck in the kernel. "
        "The adapter may need a reset or the host a reboot",
        what, process.pid,
    )


def stuck_commands() -> int:
    """Number of children that never exited after SIGKILL; reaps the ones that finally did."""
    with _stuck_lock:
        _stuck_children[:] = [p for p in _stuck_children if p.poll() is None]
        return len(_stuck_children)


def _run(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    """Run a command and never wait for it without a limit (unlike subprocess.run)."""
    process = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.communicate(timeout=KILL_GRACE)
        except subprocess.TimeoutExpired:
            _remember_stuck(process, f"Command {cmd[0]}")
            raise CommandStuck(f"Command stuck in the kernel: {' '.join(cmd)}") from None
        raise CommandTimeout(f"Command timed out: {' '.join(cmd)}") from None
    return process.returncode, stdout, stderr


_command_deadline: ContextVar[float | None] = ContextVar(
    "command_deadline", default=None,
)


@contextmanager
def command_deadline(deadline: float | None) -> Iterator[None]:
    """Bound commands in this operation without affecting other requests."""
    token = _command_deadline.set(deadline)
    try:
        yield
    finally:
        _command_deadline.reset(token)


def bounded_timeout(timeout: float) -> float:
    """Limit a timeout to the remaining command budget."""
    deadline = _command_deadline.get()
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CommandError("Deadline expired before running command")
    return min(timeout, remaining)


class ForegroundProcess:
    """A directly owned child process, independent of PID files."""

    def __init__(
        self, process: subprocess.Popen[bytes],
        classify_output: Callable[[bytes], str | None] | None = None,
        keep_lines: int = 0,
    ) -> None:
        self._process = process
        self._events: deque[str] = deque(maxlen=12)
        # Last output lines, kept only on request (hostapd_debug_dir) for diagnostics.
        self._tail: deque[str] | None = deque(maxlen=keep_lines) if keep_lines else None
        self._events_lock = Lock()
        self._reader: Thread | None = None
        if classify_output is not None and process.stdout is not None:
            self._reader = Thread(
                target=self._drain_output, args=(process.stdout, classify_output),
                name=f"child-output-{process.pid}", daemon=True,
            )
            self._reader.start()

    def _drain_output(self, stream: BinaryIO, classify: Callable[[bytes], str | None]) -> None:
        try:
            with stream:
                complete = True
                while line := stream.readline(4096):
                    if self._tail is not None:
                        with self._events_lock:
                            self._tail.append(line.decode("utf-8", "replace").rstrip("\r\n"))
                    if complete and line.endswith(b"\n") and (event := classify(line.rstrip(b"\r\n"))):
                        with self._events_lock:
                            self._events.append(event)
                    complete = line.endswith(b"\n")
        except OSError as exc:
            logger.warning("Child output reader failed (pid=%d errno=%s)", self._process.pid, exc.errno)

    def output_events(self, *, exited: bool = False) -> tuple[str, ...]:
        if exited and self._reader is not None:
            self._reader.join(timeout=0.05)
        with self._events_lock:
            return tuple(self._events)

    def output_tail(self, *, exited: bool = False) -> list[str]:
        """The last output lines kept with `keep_lines` (empty when not kept)."""
        if exited and self._reader is not None:
            self._reader.join(timeout=0.2)
        with self._events_lock:
            return list(self._tail or ())

    def poll(self) -> int | None:
        return self._process.poll()

    def stop(self) -> None:
        """Terminate and reap the child, escalating if it does not exit."""
        try:
            if self.poll() is not None:
                return
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                try:
                    self._process.wait(timeout=KILL_GRACE)
                except subprocess.TimeoutExpired:
                    _remember_stuck(self._process, f"Process {self._process.args!r}")
                    raise CommandStuck(f"Process {self._process.pid} stuck in the kernel") from None
        except subprocess.TimeoutExpired as e:
            raise CommandTimeout(f"Process {self._process.pid} did not exit") from e
        except OSError as e:
            raise CommandError(f"Could not stop process {self._process.pid}: {e}") from e


def start_foreground(
    cmd: list[str], *, classify_output: Callable[[bytes], str | None] | None = None,
    keep_lines: int = 0,
) -> ForegroundProcess:
    """Start a child, continuously draining output when a classifier is supplied."""
    bounded_timeout(1.0)
    try:
        process = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if classify_output is not None else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if classify_output is not None else subprocess.DEVNULL,
        )
        return ForegroundProcess(process, classify_output, keep_lines)
    except OSError as e:
        raise CommandError(f"Could not start {cmd[0]}: {e}") from e


def stop_process(pid: int) -> None:
    """Terminate a specific process and verify it has exited."""
    if pid <= 0:
        raise CommandError(f"Invalid process ID: {pid}")

    def running() -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    if not running():
        return
    try:
        execute_command(["kill", str(pid)])
    except CommandError:
        if running():
            raise
        return
    for _ in range(20):
        if not running():
            return
        time.sleep(0.1)
    if not running():
        return
    try:
        execute_command(["kill", "-9", str(pid)])
    except CommandError:
        if running():
            raise
        return
    for _ in range(20):
        if not running():
            return
        time.sleep(0.1)
    raise CommandError(f"Process {pid} did not exit")


def execute_command(
    cmd: list[str], check: bool = True, timeout: float = 8.0, *, exact_timeout: bool = False,
    quiet: bool = False,
) -> str:
    """
    Execute a shell command safely.
    
    Args:
        cmd: List of command arguments
        check: Raise CommandError if return code is non-zero
        timeout: Command timeout in seconds (minimum enforced to 5)
        exact_timeout: Honor the supplied timeout without applying the minimum
        quiet: The failure is an expected answer (a missing rule, nothing to
            delete, an unsupported setting): log it at debug level, not as an
            error (NET-5). CommandError is raised all the same.
        
    Returns:
        stdout as string
        
    Raises:
        CommandError: If command fails and check=True
        CommandTimeout: If the command does not finish in time (it is killed)
        CommandStuck: If the command does not exit even after SIGKILL
    """
    if not cmd:
        raise CommandError("Empty command")
    try:
        effective_timeout = bounded_timeout(
            timeout if exact_timeout else max(5.0, timeout)
        )

        returncode, stdout, stderr = _run(cmd, effective_timeout)

        if check and returncode != 0:
            (logger.debug if quiet else logger.error)(
                "Command failed: %s\nstderr: %s", " ".join(cmd), stderr,
            )
            raise CommandError(
                f"Command '{cmd[0]}' failed with code {returncode}: {stderr}",
                returncode=returncode,
            )

        return stdout

    except FileNotFoundError as e:
        raise CommandError(f"Command not found: {cmd[0]}") from e


# Seconds iptables waits for the xtables lock instead of failing at once (NET-1).
# The legacy backend takes a global lock for every call, reads included, and
# Docker, ufw or fail2ban can hold it; the nf_tables backend accepts and ignores -w.
IPTABLES_LOCK_WAIT = "5"


def execute_iptables(args: list[str], *, quiet: bool = False) -> str:
    """Execute iptables, waiting for the xtables lock. Every iptables call must go through here."""
    return execute_command(["iptables", "-w", IPTABLES_LOCK_WAIT, *args], quiet=quiet)


def rule_exists(run: Callable[..., str], check: list[str], chain: list[str] | None = None) -> bool:
    """Whether an iptables rule is installed, given its `-C` arguments (REV-3).

    `run` is execute_iptables or the ip6tables equivalent (with `quiet`). The
    answer is False only when iptables says the rule is absent (exit code 1).
    A rule that jumps to a chain that does not exist fails with exit code 2:
    pass the chain (`chain=[*table_prefix, name]`) and a missing chain also
    counts as an absent rule. Any other failure (xtables lock held, timeout)
    raises CommandError: the caller must not read it as "absent" and add the
    rule again, nor restore a network for it.
    """
    try:
        run(["-C", *check], quiet=True)   # a missing rule is a normal answer (NET-5)
        return True
    except CommandError as exc:
        if exc.returncode == 1:
            return False
        if exc.returncode != 2 or chain is None:
            raise
        try:
            run(["-S", *chain], quiet=True)
        except CommandError as listing:
            if listing.returncode == 1:   # "No chain/target/match by that name"
                return False
            raise
        raise


def execute_ip(args: list[str]) -> str:
    """Execute ip command (iproute2)."""
    return execute_command(["ip", *args])


def execute_sysctl(key: str, value: str | None = None) -> str:
    """
    Execute sysctl command.
    
    Args:
        key: sysctl key (e.g., "net.ipv4.ip_forward")
        value: Optional value to set. If None, reads current value.
    """
    if value is None:
        return execute_command(["sysctl", "-n", key])
    else:
        return execute_command(["sysctl", "-w", f"{key}={value}"])


def execute_pkill(pattern: str, signal: str | None = None) -> str:
    """Kill processes by pattern."""
    cmd = ["pkill"]
    if signal:
        cmd.extend(["-KILL", "-f"] if signal == "KILL" else ["-f"])
    cmd.append(pattern)
    return execute_command(cmd, check=False)


def execute_iw(args: list[str], *, quiet: bool = False) -> str:
    """Execute iw command (wireless tools)."""
    return execute_command(["iw", *args], quiet=quiet)


def execute_tc(args: list[str], *, quiet: bool = False) -> str:
    """Execute tc command (traffic control)."""
    return execute_command(["tc", *args], quiet=quiet)
