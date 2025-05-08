import os
import sys
import asyncio
import inspect
import pytest
from unittest.mock import MagicMock, patch

from chuk_mcp_runtime.common.mcp_tool_decorator import (
    mcp_tool,
    TOOLS_REGISTRY,
    execute_tool_async,
    execute_tool,
)
import chuk_mcp_runtime.entry as entry
from tests.conftest import MockProxyServerManager, DummyMCPServer, DummyServerRegistry, run_async

# --- Decorator tests ---

@mcp_tool(name="add_sync", description="Add two numbers (sync)")
def add_sync(x: int, y: int) -> int:
    return x + y

@mcp_tool(name="add_async", description="Add two numbers (async)")
async def add_async(x: int, y: int) -> int:
    return x + y

def test_tools_registered():
    assert "add_sync" in TOOLS_REGISTRY
    assert "add_async" in TOOLS_REGISTRY

    meta_sync = add_sync._mcp_tool
    assert meta_sync.name == "add_sync"
    assert "Add two numbers (sync)" in meta_sync.description

    meta_async = add_async._mcp_tool
    assert meta_async.name == "add_async"
    assert "Add two numbers (async)" in meta_async.description

@pytest.mark.asyncio
async def test_async_wrapper_on_sync_function():
    assert inspect.iscoroutinefunction(add_sync)
    result = await add_sync(2, 3)
    assert result == 5

def test_sync_helper_for_sync_function():
    result = add_sync.sync(4, 6)
    assert result == 10

@pytest.mark.asyncio
async def test_async_wrapper_on_async_function():
    assert inspect.iscoroutinefunction(add_async)
    result = await add_async(5, 7)
    assert result == 12

def test_sync_helper_for_async_function():
    result = add_async.sync(8, 9)
    assert result == 17

@pytest.mark.asyncio
async def test_execute_tool_async():
    r1 = await execute_tool_async("add_sync", x=10, y=20)
    assert r1 == 30
    r2 = await execute_tool_async("add_async", x=3, y=4)
    assert r2 == 7

def test_execute_tool_sync():
    r1 = execute_tool("add_sync", x=1, y=2)
    assert r1 == 3
    r2 = execute_tool("add_async", x=6, y=7)
    assert r2 == 13


# --- Runtime tests ---

@pytest.fixture(autouse=True)
def patch_entry(monkeypatch):
    monkeypatch.setattr(entry, "load_config", lambda paths, default: {})
    monkeypatch.setattr(entry, "configure_logging", lambda cfg: None)
    class DummyLogger:
        def debug(self, *a, **k): pass
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
    monkeypatch.setattr(entry, "get_logger", lambda name: DummyLogger())
    monkeypatch.setattr(entry, "find_project_root", lambda *a, **kw: "/tmp")
    monkeypatch.setattr(entry, "ServerRegistry", DummyServerRegistry)
    monkeypatch.setattr(entry, "MCPServer", DummyMCPServer)
    
    # Make sure HAS_PROXY_SUPPORT is False by default for tests
    monkeypatch.setattr(entry, "HAS_PROXY_SUPPORT", False)
    
    yield
    os.environ.pop("NO_BOOTSTRAP", None)

def test_run_runtime_default_bootstrap(monkeypatch):
    served = {}
    class SpyServer(DummyMCPServer):
        async def serve(self, custom_handlers=None):
            served['ok'] = True
            self.custom_handlers = custom_handlers
    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Override the asyncio.run to actually run the coroutine
    original_run = asyncio.run
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(entry.asyncio, "run", mock_run)

    entry.run_runtime()
    assert served.get('ok', False) is True

def test_run_runtime_skip_bootstrap_flag(monkeypatch):
    os.environ["NO_BOOTSTRAP"] = "1"
    regs = {}
    class NoBoot(DummyServerRegistry):
        def load_server_components(self):
            regs['boot'] = True
    monkeypatch.setattr(entry, "ServerRegistry", NoBoot)

    # Override the asyncio.run to actually run the coroutine
    original_run = asyncio.run
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(entry.asyncio, "run", mock_run)

    entry.run_runtime(bootstrap_components=True)
    assert 'boot' not in regs

def test_run_runtime_no_bootstrap_arg(monkeypatch):
    regs = {}
    class NoBoot(DummyServerRegistry):
        def load_server_components(self):
            regs['boot'] = True
    monkeypatch.setattr(entry, "ServerRegistry", NoBoot)

    # Override the asyncio.run to actually run the coroutine
    original_run = asyncio.run
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(entry.asyncio, "run", mock_run)

    entry.run_runtime(bootstrap_components=False)
    assert 'boot' not in regs

def test_proxy_enabled(monkeypatch):
    """Test that proxy is properly enabled when configured."""
    # Create a mock to track if ProxyServerManager was instantiated
    proxy_created = False
    
    class TrackingProxyServerManager(MockProxyServerManager):
        def __init__(self, config, project_root):
            nonlocal proxy_created
            proxy_created = True
            super().__init__(config, project_root)
    
    monkeypatch.setattr(entry, "ProxyServerManager", TrackingProxyServerManager)
    monkeypatch.setattr(entry, "HAS_PROXY_SUPPORT", True)
    monkeypatch.setattr(entry, "load_config", lambda paths, default: {"proxy": {"enabled": True}})
    
    # Mock asyncio.run to actually run the coroutine
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(entry.asyncio, "run", mock_run)
    
    # Run runtime
    entry.run_runtime()
    
    # Verify proxy was created
    assert proxy_created, "ProxyServerManager was not created"

def test_proxy_disabled(monkeypatch):
    """Test that proxy is properly disabled when not configured."""
    # Create a mock to track if ProxyServerManager was instantiated
    proxy_created = False
    
    class TrackingProxyServerManager(MockProxyServerManager):
        def __init__(self, config, project_root):
            nonlocal proxy_created
            proxy_created = True
            super().__init__(config, project_root)
    
    monkeypatch.setattr(entry, "ProxyServerManager", TrackingProxyServerManager)
    monkeypatch.setattr(entry, "HAS_PROXY_SUPPORT", True)
    monkeypatch.setattr(entry, "load_config", lambda paths, default: {"proxy": {"enabled": False}})
    
    # Mock asyncio.run to actually run the coroutine
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(entry.asyncio, "run", mock_run)
    
    # Run runtime
    entry.run_runtime()
    
    # Verify proxy was not created (disabled in config)
    assert not proxy_created, "ProxyServerManager was created even though proxy was disabled"

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

def test_proxy_server_error_handling(monkeypatch):
    """Test error handling when proxy server fails to start."""
    # Create a ProxyServerManager that raises an exception
    class FailingProxyServerManager(MockProxyServerManager):
        async def start_servers(self):
            raise RuntimeError("Failed to start proxy servers")
    
    # Create a mock to track if MCPServer.serve was called
    server_started = False
    class TrackingMCPServer(DummyMCPServer):
        async def serve(self, custom_handlers=None):
            nonlocal server_started
            server_started = True
    
    monkeypatch.setattr(entry, "ProxyServerManager", FailingProxyServerManager)
    monkeypatch.setattr(entry, "MCPServer", TrackingMCPServer)
    monkeypatch.setattr(entry, "HAS_PROXY_SUPPORT", True)
    monkeypatch.setattr(entry, "load_config", lambda paths, default: {"proxy": {"enabled": True}})
    
    # Mock asyncio.run to actually run the coroutine
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(entry.asyncio, "run", mock_run)
    
    # Run runtime - should not crash and should still start the server
    entry.run_runtime()
    
    # Verify MCPServer was still started even though proxy failed
    assert server_started, "MCPServer should start even if proxy fails"

def test_proxy_tool_registration(monkeypatch):
    """Test that proxy tools are properly registered with the MCP server."""
    # Create a test tool function
    test_tool = MagicMock(return_value="Test result")
    
    # Create a ProxyServerManager that returns our test tool
    class TestProxyServerManager(MockProxyServerManager):
        def get_all_tools(self):
            return {"proxy.test.tool": test_tool}
    
    # Create a mock MCPServer that tracks registered tools
    registered_tools = {}
    class TrackingMCPServer(DummyMCPServer):
        def register_tool(self, name, func):
            registered_tools[name] = func
    
    monkeypatch.setattr(entry, "ProxyServerManager", TestProxyServerManager)
    monkeypatch.setattr(entry, "MCPServer", TrackingMCPServer)
    monkeypatch.setattr(entry, "HAS_PROXY_SUPPORT", True)
    monkeypatch.setattr(entry, "load_config", lambda paths, default: {"proxy": {"enabled": True}})
    
    # Mock asyncio.run to actually run the coroutine
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    monkeypatch.setattr(entry.asyncio, "run", mock_run)
    
    # Run runtime
    entry.run_runtime()
    
    # Verify the tool was registered
    assert "proxy.test.tool" in registered_tools
    assert registered_tools["proxy.test.tool"] is test_tool

def test_main_success(monkeypatch, capsys):
    # Stub out run_runtime so it doesn't error
    monkeypatch.setattr(entry, "run_runtime", lambda *a, **kw: None)

    monkeypatch.setattr(sys, "argv", ["prog", "cfg.yaml"])
    # Should not raise or print errors
    entry.main(default_config={})
    assert capsys.readouterr().err == ""

def test_main_failure(monkeypatch, capsys):
    # Make run_runtime throw
    monkeypatch.setattr(entry, "run_runtime",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("bang")))
    monkeypatch.setattr(sys, "argv", ["prog"])
    with pytest.raises(SystemExit) as ei:
        entry.main(default_config={})
    assert ei.value.code == 1
    assert "Error starting CHUK MCP server: bang" in capsys.readouterr().err