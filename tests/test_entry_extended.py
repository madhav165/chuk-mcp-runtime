# tests/test_entry_extended.py
import os
import sys
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

import chuk_mcp_runtime.entry as entry
from tests.conftest import MockProxyServerManager, run_async

class DummyServerRegistry:
    def __init__(self, project_root, config):
        self.project_root = project_root
        self.config = config
        self.bootstrap_called = False
        
    async def load_server_components(self):
        """Async version of load_server_components."""
        self.bootstrap_called = True
        return {}

class DummyMCPServer:
    def __init__(self, config):
        self.config = config
        self.serve_called = False
        self.server_name = "test-server"
        self.registered_tools = []
        self.tools_registry = {}
        
    async def serve(self, custom_handlers=None):
        """Mock serve method that doesn't try to use stdio_server."""
        self.serve_called = True
        self.custom_handlers = custom_handlers
        return
        
    async def register_tool(self, name, func):
        """Mock register_tool method."""
        self.registered_tools.append(name)
        self.tools_registry[name] = func

@pytest.fixture(autouse=True)
def patch_entry(monkeypatch):
    """Set up common patches for entry module tests."""
    # Mock configuration and logging
    monkeypatch.setattr(entry, "load_config", lambda paths, default: {"proxy": {"enabled": True}})
    monkeypatch.setattr(entry, "configure_logging", lambda cfg: None)
    monkeypatch.setattr(entry, "find_project_root", lambda *a, **kw: "/tmp")
    
    # Mock the server classes
    monkeypatch.setattr(entry, "ServerRegistry", DummyServerRegistry)
    monkeypatch.setattr(entry, "MCPServer", DummyMCPServer)
    
    # Mock the proxy manager
    monkeypatch.setattr(entry, "ProxyServerManager", MockProxyServerManager)
    
    # Mock initialize_tool_registry
    mock_init_registry = AsyncMock()
    monkeypatch.setattr(entry, "initialize_tool_registry", mock_init_registry)
    
    # Mock asyncio.run to use our run_async helper
    monkeypatch.setattr(asyncio, "run", run_async)
    
    # Mock stdio_server
    # Create a dummy async context manager for stdio_server
    async def dummy_stdio_server():
        class DummyStream:
            async def read(self, n=-1):
                return b""
                
            async def write(self, data):
                return len(data)
                
            async def close(self):
                pass
        
        read_stream = DummyStream()
        write_stream = DummyStream()
        
        try:
            yield (read_stream, write_stream)
        finally:
            pass
    
    # Create a mock mcp.server.stdio module
    mock_stdio = MagicMock()
    mock_stdio.stdio_server = dummy_stdio_server
    sys.modules["mcp.server.stdio"] = mock_stdio
    
    # Reset environment variables
    yield
    
    # Clean up
    os.environ.pop("NO_BOOTSTRAP", None)
    if "mcp.server.stdio" in sys.modules:
        del sys.modules["mcp.server.stdio"]

def test_run_runtime_default_bootstrap(monkeypatch):
    """Test runtime with default bootstrap enabled."""
    # Create a server spy to track calls
    served = {}
    class SpyServer(DummyMCPServer):
        async def serve(self, custom_handlers=None):
            served['ok'] = True
            self.serve_called = True
            self.custom_handlers = custom_handlers
            
    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Run the runtime
    entry.run_runtime()
    
    # Verify the server was started
    assert served.get('ok', False) is True

def test_run_runtime_skip_bootstrap_flag(monkeypatch):
    """Test that NO_BOOTSTRAP env var prevents bootstrap."""
    # Set the environment variable
    os.environ["NO_BOOTSTRAP"] = "1"
    
    # Create a registry spy
    registry_called = {}
    class SpyRegistry(DummyServerRegistry):
        async def load_server_components(self):
            registry_called['bootstrap'] = True
            return {}
            
    monkeypatch.setattr(entry, "ServerRegistry", SpyRegistry)

    # Run with bootstrap_components=True
    entry.run_runtime(bootstrap_components=True)
    
    # Should not have called load_server_components
    assert 'bootstrap' not in registry_called

def test_run_runtime_no_bootstrap_arg(monkeypatch):
    """Test that bootstrap_components=False prevents bootstrap."""
    # Create a registry spy
    registry_called = {}
    class SpyRegistry(DummyServerRegistry):
        async def load_server_components(self):
            registry_called['bootstrap'] = True
            return {}
            
    monkeypatch.setattr(entry, "ServerRegistry", SpyRegistry)

    # Run with bootstrap_components=False
    entry.run_runtime(bootstrap_components=False)
    
    # Should not have called load_server_components
    assert 'bootstrap' not in registry_called

def test_proxy_integration(monkeypatch):
    """Test proxy tool registration with the MCP server."""
    # Create a spy server to track tool registration
    server_instance = None
    class SpyServer(DummyMCPServer):
        def __init__(self, config):
            super().__init__(config)
            nonlocal server_instance
            server_instance = self
            
    monkeypatch.setattr(entry, "MCPServer", SpyServer)
    
    # Create a test proxy manager
    class TestProxyManager(MockProxyServerManager):
        async def get_all_tools(self):
            return {"proxy.test_server.tool": AsyncMock(return_value="test result")}
            
    monkeypatch.setattr(entry, "ProxyServerManager", TestProxyManager)
    
    # Run the runtime
    entry.run_runtime()
    
    # Verify that the proxy tool was registered
    assert server_instance is not None
    assert server_instance.registered_tools, "No tools were registered"
    assert "proxy.test_server.tool" in server_instance.registered_tools

def test_main_success(monkeypatch, capsys):
    """Test successful execution of main function."""
    # Stub out run_runtime_async to prevent errors
    async def mock_run_runtime_async(*args, **kwargs):
        return None
        
    monkeypatch.setattr(entry, "run_runtime_async", mock_run_runtime_async)

    # Set command line arguments
    monkeypatch.setattr(sys, "argv", ["prog", "cfg.yaml"])
    
    # Run main
    entry.main(default_config={})
    
    # Should not have any errors
    assert capsys.readouterr().err == ""

def test_main_failure(monkeypatch, capsys):
    """Test handling of errors in main function."""
    # Create a mock that raises an exception
    async def mock_run_runtime_error(*args, **kwargs):
        raise RuntimeError("bang")
        
    monkeypatch.setattr(entry, "run_runtime_async", mock_run_runtime_error)
    
    # Set command line arguments
    monkeypatch.setattr(sys, "argv", ["prog"])
    
    # Should exit with code 1
    with pytest.raises(SystemExit) as ei:
        entry.main(default_config={})
        
    assert ei.value.code == 1
    
    # Should print the error message
    assert "Error starting CHUK MCP server: bang" in capsys.readouterr().err