import logging
import os
import subprocess
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock, Thread
from typing import BinaryIO

logger = logging.getLogger(__name__)


class CommandError(Exception):
    """Exception raised when shell command execution fails."""


class CommandTimeout(CommandError):
    """The command did not finish before its deadline."""


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
    ) -> None:
        self._process = process
        self._events: deque[str] = deque(maxlen=12)
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
                self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired as e:
            raise CommandTimeout(f"Process {self._process.pid} did not exit") from e
        except OSError as e:
            raise CommandError(f"Could not stop process {self._process.pid}: {e}") from e


def start_foreground(
    cmd: list[str], *, classify_output: Callable[[bytes], str | None] | None = None,
) -> ForegroundProcess:
    """Start a child, continuously draining output when a classifier is supplied."""
    bounded_timeout(1.0)
    try:
        process = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if classify_output is not None else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if classify_output is not None else subprocess.DEVNULL,
        )
        return ForegroundProcess(process, classify_output)
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
) -> str:
    """
    Execute a shell command safely.
    
    Args:
        cmd: List of command arguments
        check: Raise CommandError if return code is non-zero
        timeout: Command timeout in seconds (minimum enforced to 5)
        exact_timeout: Honor the supplied timeout without applying the minimum
        
    Returns:
        stdout as string
        
    Raises:
        CommandError: If command fails and check=True
    """
    if not cmd:
        raise CommandError("Empty command")
    try:
        effective_timeout = bounded_timeout(
            timeout if exact_timeout else max(5.0, timeout)
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=effective_timeout
        )
        
        if check and result.returncode != 0:
            logger.error(
                f"Command failed: {' '.join(cmd)}\nstderr: {result.stderr}"
            )
            raise CommandError(
                f"Command '{cmd[0]}' failed with code {result.returncode}: {result.stderr}"
            )
        
        return result.stdout
    
    except subprocess.TimeoutExpired as e:
        raise CommandTimeout(f"Command timed out: {' '.join(cmd)}") from e
    except FileNotFoundError as e:
        raise CommandError(f"Command not found: {cmd[0]}") from e


def execute_iptables(args: list[str]) -> str:
    """Execute iptables command."""
    return execute_command(["iptables", *args])


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


def execute_iw(args: list[str]) -> str:
    """Execute iw command (wireless tools)."""
    return execute_command(["iw", *args])


def execute_tc(args: list[str]) -> str:
    """Execute tc command (traffic control)."""
    return execute_command(["tc", *args])
