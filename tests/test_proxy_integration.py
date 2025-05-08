import pytest
import asyncio
from unittest.mock import MagicMock, patch

import chuk_mcp_runtime.entry as entry
from chuk_mcp_runtime.server.server import MCPServer
from tests.conftest import MockProxyServerManager, run_async

# Mock classes for testing
class MockServerRegistry:
    def __init__(self, project_root, config):
        self.project_root = project_root
        self.config = config
        
    def load_server_components(self):
        pass

class MockMCPServer:
    def __init__(self, config):
        self.config = config
        self.server_name = "mock-server"
        self.tools_registry = {}
        self.registered_tools = []
        
    def register_tool(self, name, func):
        self.registered_tools.append(name)
        self.tools_registry[name] = func
        
    async def serve(self, custom_handlers=None):
        self.custom_handlers = custom_handlers

@pytest.fixture
def setup_mocks(monkeypatch):
    """Set up mocks for testing."""
    # Mock config and logging
    monkeypatch.setattr(entry, "load_config", 
                       lambda paths, default: {"proxy": {"enabled": True}})
    monkeypatch.setattr(entry, "configure_logging", lambda cfg: None)
    monkeypatch.setattr(entry, "find_project_root", lambda: "/tmp")
    
    # Mock server components
    monkeypatch.setattr(entry, "ServerRegistry", MockServerRegistry)
    monkeypatch.setattr(entry, "MCPServer", MockMCPServer)
    
    # Set up proxy
    monkeypatch.setattr(entry, "ProxyServerManager", MockProxyServerManager)
    monkeypatch.setattr(entry, "HAS_PROXY_SUPPORT", True)
    
    # Return the mocked objects for test use
    return {
        "config": {"proxy": {"enabled": True}},
        "project_root": "/tmp"
    }

@pytest.fixture
def mock_async_run(monkeypatch):
    """Mock asyncio.run to capture the coroutine for testing."""
    async_run_called = False
    coro_obj = None
    
    def capture_run(coro):
        nonlocal async_run_called, coro_obj
        async_run_called = True
        coro_obj = coro
        
        # Actually run the coroutine
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    monkeypatch.setattr(asyncio, "run", capture_run)
    
    return lambda: (async_run_called, coro_obj)

def test_proxy_enabled(setup_mocks, mock_async_run):
    """Test that proxy is properly enabled when configured."""
    # Run the runtime
    entry.run_runtime()
    
    # Get the capture information
    async_run_called, coro = mock_async_run()
    
    # Verify asyncio.run was called
    assert async_run_called, "asyncio.run was not called"

def test_proxy_disabled(setup_mocks, monkeypatch):
    """Test that proxy is properly disabled when not configured."""
    # Disable proxy in config
    monkeypatch.setattr(entry, "load_config", 
                       lambda paths, default: {"proxy": {"enabled": False}})
    
    # Create a mock to capture the MCPServer instance
    server_instance = None
    
    class MockMCPServerCapture(MockMCPServer):
        def __init__(self, config):
            super().__init__(config)
            nonlocal server_instance
            server_instance = self
    
    monkeypatch.setattr(entry, "MCPServer", MockMCPServerCapture)
    
    # Run the runtime with a real asyncio.run
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(asyncio, "run", mock_run)
    
    # Run runtime
    entry.run_runtime()
    
    # Verify server was created
    assert server_instance is not None, "MCPServer was not created"
    # No custom handlers should be set (since proxy is disabled)
    assert not hasattr(server_instance, 'custom_handlers') or server_instance.custom_handlers is None

def test_need_proxy_function():
    """Test the _need_proxy helper function."""
    # Test with proxy enabled and dependencies available
    with patch.object(entry, 'HAS_PROXY_SUPPORT', True):
        assert entry._need_proxy({"proxy": {"enabled": True}}) is True
        assert entry._need_proxy({"proxy": {"enabled": False}}) is False
        assert entry._need_proxy({}) is False
    
    # Test with proxy enabled but dependencies not available
    with patch.object(entry, 'HAS_PROXY_SUPPORT', False):
        assert entry._need_proxy({"proxy": {"enabled": True}}) is False
        assert entry._need_proxy({"proxy": {"enabled": False}}) is False

def test_proxy_server_error_handling(setup_mocks, monkeypatch):
    """Test error handling when proxy server fails to start."""
    # Create a ProxyServerManager that raises an exception
    class FailingProxyServerManager(MockProxyServerManager):
        async def start_servers(self):
            raise RuntimeError("Failed to start proxy servers")
    
    monkeypatch.setattr(entry, "ProxyServerManager", FailingProxyServerManager)
    
    # Create a mock MCPServer to verify it still runs even if proxy fails
    server_started = False
    
    class VerifyMCPServer(MockMCPServer):
        async def serve(self, custom_handlers=None):
            nonlocal server_started
            server_started = True
    
    monkeypatch.setattr(entry, "MCPServer", VerifyMCPServer)
    
    # Run the runtime with a real asyncio.run
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(asyncio, "run", mock_run)
    
    # Run runtime - should not crash
    entry.run_runtime()
    
    # Verify MCPServer was still started even though proxy failed
    assert server_started, "MCPServer should start even if proxy fails"

def test_proxy_tool_registration(setup_mocks, monkeypatch):
    """Test that proxy tools are properly registered with the MCP server."""
    # Create a test tool function
    test_tool = MagicMock(return_value="Test result")
    
    # Create a ProxyServerManager that returns our test tool
    class TestProxyServerManager(MockProxyServerManager):
        def get_all_tools(self):
            return {"proxy.test.tool": test_tool}
    
    monkeypatch.setattr(entry, "ProxyServerManager", TestProxyServerManager)
    
    # Create a mock MCPServer that tracks registered tools
    registered_tools = {}
    
    class ToolTrackingMCPServer(MockMCPServer):
        def register_tool(self, name, func):
            registered_tools[name] = func
            
    monkeypatch.setattr(entry, "MCPServer", ToolTrackingMCPServer)
    
    # Run the runtime with a real asyncio.run
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(asyncio, "run", mock_run)
    
    # Run runtime
    entry.run_runtime()
    
    # Verify the tool was registered
    assert "proxy.test.tool" in registered_tools
    assert registered_tools["proxy.test.tool"] is test_tool