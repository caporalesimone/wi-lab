import subprocess
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, List, Optional

logger = logging.getLogger(__name__)


class CommandError(Exception):
    """Exception raised when shell command execution fails."""
    pass


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

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

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


def start_foreground(cmd: list[str]) -> ForegroundProcess:
    """Start a child without an output pipe that could block the daemon."""
    bounded_timeout(1.0)
    try:
        return ForegroundProcess(subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))
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


def execute_iptables(args: List[str]) -> str:
    """Execute iptables command."""
    return execute_command(["iptables", *args])


def execute_ip(args: List[str]) -> str:
    """Execute ip command (iproute2)."""
    return execute_command(["ip", *args])


def execute_sysctl(key: str, value: Optional[str] = None) -> str:
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


def execute_pkill(pattern: str, signal: Optional[str] = None) -> str:
    """Kill processes by pattern."""
    cmd = ["pkill"]
    if signal:
        cmd.extend(["-KILL", "-f"] if signal == "KILL" else ["-f"])
    cmd.append(pattern)
    return execute_command(cmd, check=False)


def execute_iw(args: List[str]) -> str:
    """Execute iw command (wireless tools)."""
    return execute_command(["iw", *args])


def execute_tc(args: List[str]) -> str:
    """Execute tc command (traffic control)."""
    return execute_command(["tc", *args])
