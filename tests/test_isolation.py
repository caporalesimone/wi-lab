"""Tests for network isolation functionality."""

import pytest
from wilab.network.isolation import IsolationManager
from wilab.network.commands import CommandError
from unittest.mock import MagicMock, patch


class TestIsolationManagerInit:
    """Tests for IsolationManager initialization."""
    
    def test_isolation_manager_init(self):
        """Test isolation manager initialization."""
        manager = IsolationManager()
        assert manager._active_subnets == set()
    
    def test_get_active_subnets_empty(self):
        """Test getting active subnets when none exist."""
        manager = IsolationManager()
        assert manager.get_active_subnets() == []


class TestAddNetwork:
    """Tests for adding network isolation rules."""
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_add_first_network(self, mock_iptables):
        """Test adding isolation rules for first network."""
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        
        # No iptables calls for first network (no other networks to isolate from)
        assert mock_iptables.call_count == 0
        assert '192.168.10.0/24' in manager._active_subnets
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_add_second_network(self, mock_iptables):
        """Test adding isolation rules for second network."""
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        manager.add_network('192.168.11.0/24')
        
        # Should create 2 rules: 10->11 and 11->10
        assert mock_iptables.call_count == 2
        
        # Verify blocking calls
        calls = mock_iptables.call_args_list
        assert any('-s' in str(call) and '192.168.10.0/24' in str(call) and '192.168.11.0/24' in str(call) 
                   for call in calls)
        assert any('-s' in str(call) and '192.168.11.0/24' in str(call) and '192.168.10.0/24' in str(call) 
                   for call in calls)
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_add_third_network(self, mock_iptables):
        """Test adding isolation rules for third network."""
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        manager.add_network('192.168.11.0/24')
        mock_iptables.reset_mock()
        
        manager.add_network('192.168.12.0/24')
        
        # Should create 4 rules: 12->10, 10->12, 12->11, 11->12
        assert mock_iptables.call_count == 4
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_add_duplicate_network(self, mock_iptables):
        """Test adding same network twice doesn't create duplicate rules."""
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        manager.add_network('192.168.10.0/24')
        
        # No rules for duplicate
        assert mock_iptables.call_count == 0
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_add_network_iptables_error(self, mock_iptables):
        """Test that iptables errors don't crash the manager."""
        mock_iptables.side_effect = CommandError("iptables failed", 1)
        
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        manager.add_network('192.168.11.0/24')
        
        # Should handle error gracefully and still track networks
        assert '192.168.10.0/24' in manager._active_subnets
        assert '192.168.11.0/24' in manager._active_subnets


class TestRemoveNetwork:
    """Tests for removing network isolation rules."""
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_remove_network(self, mock_iptables):
        """Test removing isolation rules for a network."""
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        manager.add_network('192.168.11.0/24')
        mock_iptables.reset_mock()
        
        manager.remove_network('192.168.10.0/24')
        
        # Should remove 2 rules: 10->11 and 11->10
        assert mock_iptables.call_count == 2
        assert '192.168.10.0/24' not in manager._active_subnets
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_remove_nonexistent_network(self, mock_iptables):
        """Test removing network that wasn't added."""
        manager = IsolationManager()
        manager.remove_network('192.168.10.0/24')
        
        # Should not call iptables
        assert mock_iptables.call_count == 0
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_remove_network_iptables_error(self, mock_iptables):
        """Test that iptables errors during removal are handled gracefully."""
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        manager.add_network('192.168.11.0/24')
        mock_iptables.reset_mock()
        
        # Make iptables fail
        mock_iptables.side_effect = CommandError("Rule not found", 1)
        
        manager.remove_network('192.168.10.0/24')
        
        # Should still remove from tracking
        assert '192.168.10.0/24' not in manager._active_subnets


class TestFlushAll:
    """Tests for flushing all isolation rules."""
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_flush_all(self, mock_iptables):
        """Test flushing all isolation rules."""
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        manager.add_network('192.168.11.0/24')
        manager.add_network('192.168.12.0/24')
        mock_iptables.reset_mock()
        
        manager.flush_all()
        
        # Should remove all networks
        assert len(manager._active_subnets) == 0
        assert manager.get_active_subnets() == []


class TestIptablesRuleFormat:
    """Tests for correct iptables rule formatting."""
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_block_rule_format(self, mock_iptables):
        """Test that blocking rules have correct iptables format."""
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        manager.add_network('192.168.11.0/24')
        
        # Verify rule format: iptables -A FORWARD -s <src> -d <dst> -j DROP
        # (Note: Changed from -I FORWARD 1 to -A FORWARD for safety)
        calls = mock_iptables.call_args_list
        for call in calls:
            args = call[0][0]  # First positional argument (list of args)
            assert '-A' in args  # Append, not insert
            assert 'FORWARD' in args
            assert '-s' in args
            assert '-d' in args
            assert '-j' in args
            assert 'DROP' in args
    
    @patch('wilab.network.isolation.execute_iptables')
    def test_unblock_rule_format(self, mock_iptables):
        """Test that unblocking rules have correct iptables format."""
        manager = IsolationManager()
        manager.add_network('192.168.10.0/24')
        manager.add_network('192.168.11.0/24')
        mock_iptables.reset_mock()
        
        manager.remove_network('192.168.10.0/24')
        
        # Verify rule format: iptables -D FORWARD -s <src> -d <dst> -j DROP
        calls = mock_iptables.call_args_list
        for call in calls:
            args = call[0][0]  # First positional argument (list of args)
            assert '-D' in args
            assert 'FORWARD' in args
            assert '-s' in args
            assert '-d' in args
            assert '-j' in args
            assert 'DROP' in args
