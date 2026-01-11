import subprocess
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class CommandError(Exception):
    """Exception raised when shell command execution fails."""
    pass


def execute_command(cmd: List[str], check: bool = True) -> str:
    """
    Execute a shell command safely.
    
    Args:
        cmd: List of command arguments
        check: Raise CommandError if return code is non-zero
        
    Returns:
        stdout as string
        
    Raises:
        CommandError: If command fails and check=True
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=15  # Longer timeout for hostapd initialization
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
        raise CommandError(f"Command timed out: {' '.join(cmd)}") from e
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
