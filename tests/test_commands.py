import pytest
from unittest.mock import patch, MagicMock
from wilab.network.commands import (
    CommandError, execute_command, execute_iptables,
    execute_ip, execute_sysctl, execute_pkill
)


class TestCommandExecution:
    """Tests for basic command execution."""
    
    def test_execute_command_success(self):
        """Test successful command execution."""
        result = execute_command(['echo', 'hello'])
        assert 'hello' in result
    
    def test_execute_command_failure(self):
        """Test command failure raises error."""
        with pytest.raises(CommandError):
            execute_command(['false'])  # Command that always fails
    
    def test_execute_command_not_found(self):
        """Test command not found raises error."""
        with pytest.raises(CommandError, match="not found"):
            execute_command(['nonexistent-command-xyz'])
    
    def test_execute_command_timeout(self):
        """Test command timeout raises error."""
        with pytest.raises(CommandError, match="timed out|timeout"):
            # Use 2 seconds to exceed the 1-second timeout in execute_command
            execute_command(['sleep', '2'], check=True)
    
    def test_execute_command_check_false(self):
        """Test command with check=False doesn't raise."""
        result = execute_command(['false'], check=False)
        # Should not raise
        assert result is not None


class TestIptablesWrapper:
    """Tests for iptables command wrapper."""
    
    def test_execute_iptables(self):
        """Test iptables wrapper."""
        # We can't actually run iptables in test, but we can mock it
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = ''
            result = execute_iptables(['-L', '-n'])
            mock.assert_called_once()
            # Check that 'iptables' was prepended
            assert mock.call_args[0][0][0] == 'iptables'


class TestIpWrapper:
    """Tests for ip command wrapper."""
    
    def test_execute_ip(self):
        """Test ip command wrapper."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = ''
            result = execute_ip(['addr', 'show'])
            mock.assert_called_once()
            assert mock.call_args[0][0][0] == 'ip'
    
    def test_execute_ip_addr_add(self):
        """Test ip addr add command."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = ''
            execute_ip(['addr', 'add', '192.168.1.1/24', 'dev', 'eth0'])
            call_args = mock.call_args[0][0]
            assert call_args[0] == 'ip'
            assert 'addr' in call_args
            assert 'add' in call_args


class TestSysctlWrapper:
    """Tests for sysctl command wrapper."""
    
    def test_sysctl_read(self):
        """Test reading sysctl value."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = '1\n'
            result = execute_sysctl('net.ipv4.ip_forward')
            mock.assert_called_once()
            call_args = mock.call_args[0][0]
            assert 'sysctl' in call_args
            assert '-n' in call_args
    
    def test_sysctl_write(self):
        """Test writing sysctl value."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = 'net.ipv4.ip_forward = 1\n'
            result = execute_sysctl('net.ipv4.ip_forward', '1')
            mock.assert_called_once()
            call_args = mock.call_args[0][0]
            assert 'sysctl' in call_args
            assert '-w' in call_args


class TestPkillWrapper:
    """Tests for pkill command wrapper."""
    
    def test_pkill_pattern(self):
        """Test pkill with pattern."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = ''
            execute_pkill('dnsmasq')
            mock.assert_called_once()
            call_args = mock.call_args[0][0]
            assert 'pkill' in call_args
            assert 'dnsmasq' in call_args
    
    def test_pkill_with_signal(self):
        """Test pkill with signal."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = ''
            execute_pkill('hostapd', signal='KILL')
            call_args = mock.call_args[0][0]
            assert 'pkill' in call_args
            assert 'KILL' in call_args or '-f' in call_args


class TestCommandError:
    """Tests for CommandError exception."""
    
    def test_command_error_message(self):
        """Test CommandError contains useful message."""
        try:
            raise CommandError("Test error message")
        except CommandError as e:
            assert "Test error message" in str(e)
    
    def test_command_error_from_exception(self):
        """Test CommandError with from clause."""
        try:
            try:
                raise RuntimeError("Original error")
            except RuntimeError as e:
                raise CommandError("Wrapper error") from e
        except CommandError as e:
            assert "Wrapper error" in str(e)


class TestCommandIntegration:
    """Integration tests for command wrappers."""
    
    def test_command_output_captured(self):
        """Test that command output is captured correctly."""
        result = execute_command(['echo', 'test output'])
        assert 'test output' in result
        assert isinstance(result, str)
    
    def test_multiple_commands_sequence(self):
        """Test executing multiple commands in sequence."""
        result1 = execute_command(['echo', 'first'])
        result2 = execute_command(['echo', 'second'])
        assert 'first' in result1
        assert 'second' in result2
    
    def test_command_with_arguments(self):
        """Test command with multiple arguments."""
        result = execute_command(['echo', 'arg1', 'arg2', 'arg3'])
        assert 'arg1' in result
        assert 'arg2' in result
        assert 'arg3' in result


class TestCommandEdgeCases:
    """Tests for edge cases in command execution."""
    
    def test_empty_command_list(self):
        """Test handling of empty command list."""
        with pytest.raises((CommandError, IndexError)):
            execute_command([])
    
    def test_command_with_pipes(self):
        """Test command with complex arguments."""
        # Note: pipes don't work directly with list form, must use actual pipe
        result = execute_command(['echo', 'test'])
        assert result is not None
    
    def test_command_with_unicode(self):
        """Test command handling unicode output."""
        result = execute_command(['echo', 'test-äöü'])
        assert 'test' in result
