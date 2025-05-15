# tests/test_entry_basic.py
"""
Test module for basic functionality of chuk_mcp_runtime entry point.

Tests core functions and mock setup for the MCP runtime.
"""
import pytest
import sys
from unittest.mock import MagicMock, patch

# Import our common test mocks
from tests.common.test_mocks import (
    MockProxyServerManager, 
    MockMCPServer,
    MockServerRegistry,
    DummyMCPServer,
    DummyServerRegistry,
    AsyncMock,
    run_async
)

# Import the entry module with our mocks already installed
from tests.common.test_mocks import entry_module as entry

def test_need_proxy_function():
    """Test that the _need_proxy function correctly identifies proxy config."""
    # Test with HAS_PROXY_SUPPORT = True (default)
    assert entry._need_proxy({"proxy": {"enabled": True}}) is True
    assert entry._need_proxy({"proxy": {"enabled": False}}) is False
    assert entry._need_proxy({}) is False
    
    # Test with HAS_PROXY_SUPPORT = False
    with patch.object(entry, 'HAS_PROXY_SUPPORT', False):
        assert entry._need_proxy({"proxy": {"enabled": True}}) is False
        assert entry._need_proxy({"proxy": {"enabled": False}}) is False
        assert entry._need_proxy({}) is False
    
def test_import_paths():
    """Test that the imports were mocked correctly."""
    assert "chuk_tool_processor" in sys.modules
    assert "chuk_tool_processor.mcp" in sys.modules
    
def test_proxy_server_manager_mock():
    """Test that ProxyServerManager is mocked correctly."""
    # Get the ProxyServerManager from entry
    assert entry.ProxyServerManager is MockProxyServerManager
    
    # Create an instance of the mocked class
    proxy_mgr = entry.ProxyServerManager({}, "/tmp")
    assert hasattr(proxy_mgr, "running") or hasattr(proxy_mgr, "running_servers")
    
    # Test that methods exist
    assert hasattr(proxy_mgr, "start_servers")
    assert hasattr(proxy_mgr, "stop_servers")
    assert hasattr(proxy_mgr, "get_all_tools")
    
    # Test that process_text method exists (added for tool naming compatibility)
    assert hasattr(proxy_mgr, "process_text")

def test_tool_naming_compatibility():
    """Test that the proxy manager supports tool naming compatibility."""
    # Create a proxy manager with tools in different formats
    proxy_mgr = MockProxyServerManager({
        "proxy": {
            "enabled": True,
            "openai_compatible": True
        }
    }, "/tmp")
    
    # Add a tool function that returns a mock response
    test_tool = AsyncMock(return_value="Tool response")
    proxy_mgr.tools = {
        "proxy.test.tool": test_tool
    }
    
    # Test get_all_tools (async function)
    tools = run_async(proxy_mgr.get_all_tools())
    assert "proxy.test.tool" in tools
    
    # Test process_text functionality (async function)
    result = run_async(proxy_mgr.process_text("Test text"))
    assert result[0]["processed"] is True
    assert result[0]["text"] == "Test text"
    
    # Test call_tool with different naming formats (async function)
    # With dot notation
    result1 = run_async(proxy_mgr.call_tool("proxy.test.tool", query="test"))
    assert "result" in result1.lower() or "response" in result1.lower()
    
    # With underscore notation
    result2 = run_async(proxy_mgr.call_tool("test_tool", query="test"))
    assert "result" in result2.lower() or "response" in result2.lower()

def test_initialize_tool_registry_called():
    """Test that initialize_tool_registry is called during runtime startup."""
    # Using context managers is cleaner and safer
    with patch('chuk_mcp_runtime.entry.ServerRegistry', DummyServerRegistry), \
         patch('chuk_mcp_runtime.entry.initialize_tool_registry') as mock_init, \
         patch('chuk_mcp_runtime.entry.load_config', return_value={"proxy": {"enabled": False}}), \
         patch('chuk_mcp_runtime.entry.configure_logging'), \
         patch('chuk_mcp_runtime.entry.find_project_root', return_value="/tmp"), \
         patch('asyncio.run', side_effect=run_async):
        
        # Create a custom server that won't try to use stdio
        server = DummyMCPServer({"server": {"type": "stdio"}})
        
        # Patch MCPServer separately to use our custom instance
        with patch('chuk_mcp_runtime.entry.MCPServer', return_value=server):
            # Make initialize_tool_registry an async mock
            async def mock_init_async(*args, **kwargs):
                return None
            mock_init.side_effect = mock_init_async
            
            # Run the runtime
            entry.run_runtime()
            
            # Check that initialize_tool_registry was called
            assert mock_init.called