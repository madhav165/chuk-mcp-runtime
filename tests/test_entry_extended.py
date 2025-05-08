import os
import sys
import asyncio
import pytest

import chuk_mcp_runtime.entry as entry
from tests.conftest import MockProxyServerManager

class DummyServerRegistry:
    def __init__(self, project_root, config):
        self.bootstrap_called = False
    def load_server_components(self):
        self.bootstrap_called = True

class DummyMCPServer:
    def __init__(self, config):
        self.serve_called = False
        # Add server_name for compatibility with entry.py
        self.server_name = "test-server"
        
    async def serve(self, custom_handlers=None):
        self.serve_called = True
        self.custom_handlers = custom_handlers

@pytest.fixture(autouse=True)
def patch_entry(monkeypatch):
    monkeypatch.setattr(entry, "load_config", lambda paths, default: {"proxy": {"enabled": True}})
    monkeypatch.setattr(entry, "configure_logging", lambda cfg: None)
    monkeypatch.setattr(entry, "find_project_root", lambda *a, **kw: "/tmp")
    monkeypatch.setattr(entry, "ServerRegistry", DummyServerRegistry)
    monkeypatch.setattr(entry, "MCPServer", DummyMCPServer)
    
    # ProxyServerManager should already be patched by conftest.py,
    # but we can ensure it here as well for clarity
    monkeypatch.setattr(entry, "ProxyServerManager", MockProxyServerManager)
    
    # Mock asyncio.run to avoid actually running the event loop
    def mock_run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    monkeypatch.setattr(entry.asyncio, "run", mock_run)
    
    # Reset environment variables
    yield
    os.environ.pop("NO_BOOTSTRAP", None)

def test_run_runtime_default_bootstrap(monkeypatch):
    served = {}
    class SpyServer(DummyMCPServer):
        async def serve(self, custom_handlers=None):
            served['ok'] = True
            self.custom_handlers = custom_handlers
            
    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    entry.run_runtime()
    assert served.get('ok', False) is True

def test_run_runtime_skip_bootstrap_flag(monkeypatch):
    os.environ["NO_BOOTSTRAP"] = "1"
    regs = {}
    class NoBoot(DummyServerRegistry):
        def load_server_components(self):
            regs['boot'] = True
    monkeypatch.setattr(entry, "ServerRegistry", NoBoot)

    entry.run_runtime(bootstrap_components=True)
    assert 'boot' not in regs

def test_run_runtime_no_bootstrap_arg(monkeypatch):
    regs = {}
    class NoBoot(DummyServerRegistry):
        def load_server_components(self):
            regs['boot'] = True
    monkeypatch.setattr(entry, "ServerRegistry", NoBoot)

    entry.run_runtime(bootstrap_components=False)
    assert 'boot' not in regs

def test_proxy_integration(monkeypatch):
    # Test that proxy tools are registered with the MCP server
    server_instance = None
    class SpyServer(DummyMCPServer):
        def __init__(self, config):
            super().__init__(config)
            nonlocal server_instance
            server_instance = self
            self.registered_tools = []
            
        def register_tool(self, name, func):
            self.registered_tools.append(name)
            
    monkeypatch.setattr(entry, "MCPServer", SpyServer)
    
    # Run the runtime
    entry.run_runtime()
    
    # Verify that the proxy tool was registered
    assert server_instance is not None
    assert "proxy.test_server.tool" in server_instance.registered_tools
    
    # Verify that custom handlers were set up
    assert server_instance.custom_handlers is not None
    assert "handle_proxy_text" in server_instance.custom_handlers

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