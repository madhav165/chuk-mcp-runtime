# tests/test_entry.py
import pytest
import sys
from unittest.mock import MagicMock, patch

# Import entry will work because we've mocked the imports in conftest.py
import chuk_mcp_runtime.entry as entry
from tests.conftest import MockProxyServerManager, DummyMCPServer, DummyServerRegistry

def test_need_proxy_function():
    """Test that the _need_proxy function correctly identifies proxy config."""
    assert entry._need_proxy({"proxy": {"enabled": True}}) is True
    assert entry._need_proxy({"proxy": {"enabled": False}}) is False
    assert entry._need_proxy({}) is False
    
def test_import_paths():
    """Test that the imports were mocked correctly."""
    assert "chuk_tool_processor" in sys.modules
    assert "chuk_tool_processor.mcp" in sys.modules
    assert "chuk_mcp_runtime.proxy.manager" in sys.modules
    
def test_proxy_server_manager_mock():
    """Test that ProxyServerManager is mocked correctly."""
    # Get the ProxyServerManager from entry
    assert entry.ProxyServerManager is MockProxyServerManager
    
    # Create an instance of the mocked class
    proxy_mgr = entry.ProxyServerManager({}, "/tmp")
    assert proxy_mgr.running_servers == {}
    
    # Test that methods exist
    assert hasattr(proxy_mgr, "start_servers")
    assert hasattr(proxy_mgr, "stop_servers")
    assert hasattr(proxy_mgr, "get_all_tools")
    assert hasattr(proxy_mgr, "process_text")
