import os
import sys
import asyncio
import inspect
import pytest

from chuk_mcp_runtime.common.mcp_tool_decorator import (
    mcp_tool,
    TOOLS_REGISTRY,
    execute_tool_async,
    execute_tool,
)
import chuk_mcp_runtime.entry as entry

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

class DummyServerRegistry:
    def __init__(self, project_root, config):
        self.bootstrap_called = False
    def load_server_components(self):
        self.bootstrap_called = True

class DummyMCPServer:
    def __init__(self, config):
        self.serve_called = False
    async def serve(self):
        self.serve_called = True

@pytest.fixture(autouse=True)
def patch_entry(monkeypatch):
    monkeypatch.setattr(entry, "load_config", lambda paths, default: {})
    monkeypatch.setattr(entry, "configure_logging", lambda cfg: None)
    class DummyLogger:
        def debug(self, *a, **k): pass
        def info(self, *a, **k): pass
    monkeypatch.setattr(entry, "get_logger", lambda name: DummyLogger())
    monkeypatch.setattr(entry, "find_project_root", lambda *a, **kw: "/tmp")
    monkeypatch.setattr(entry, "ServerRegistry", DummyServerRegistry)
    monkeypatch.setattr(entry, "MCPServer", DummyMCPServer)
    yield
    os.environ.pop("NO_BOOTSTRAP", None)

def test_run_runtime_default_bootstrap(monkeypatch):
    served = {}
    class SpyServer(DummyMCPServer):
        async def serve(self):
            served['ok'] = True
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

def test_main_success(monkeypatch, capsys):
    # Stub out run_runtime so it doesn't error
    monkeypatch.setattr(entry, "run_runtime", lambda *a, **kw: None)
    # Patch the asyncio.run inside entry.main to a no-op
    monkeypatch.setattr(entry.asyncio, "run", lambda coro: None)

    monkeypatch.setattr(sys, "argv", ["prog", "cfg.yaml"])
    # Should not raise or print errors
    entry.main(default_config={})
    assert capsys.readouterr().err == ""

def test_main_failure(monkeypatch, capsys):
    # Make run_runtime throw
    monkeypatch.setattr(entry, "run_runtime",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("bang")))
    monkeypatch.setattr(entry.asyncio, "run", lambda coro: None)
    monkeypatch.setattr(sys, "argv", ["prog"])
    with pytest.raises(SystemExit) as ei:
        entry.main(default_config={})
    assert ei.value.code == 1
    assert "Error starting CHUK MCP server: bang" in capsys.readouterr().err