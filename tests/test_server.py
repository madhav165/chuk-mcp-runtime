# tests/test_server.py
import pytest
import asyncio
from contextlib import asynccontextmanager

from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool

# --- Setup fake Server and stdio_server ---

created_servers = []

class FakeServer:
    def __init__(self, name):
        # Capture the instance so tests can inspect it
        created_servers.append(self)
        self.name = name
        self.handlers = {}
        # Add server_name for compatibility with entry.py
        self.server_name = name

    def list_tools(self):
        def decorator(fn):
            self.handlers['list_tools'] = fn
            return fn
        return decorator

    def call_tool(self):
        def decorator(fn):
            self.handlers['call_tool'] = fn
            return fn
        return decorator
    
    def process_text(self):
        def decorator(fn):
            self.handlers['process_text'] = fn
            return fn
        return decorator

    def create_initialization_options(self):
        return {}

    async def run(self, read, write, options):
        # No-op so serve() completes immediately
        return

@asynccontextmanager
async def dummy_stdio():
    yield (None, None)

# --- Dummy tools for testing ---

@mcp_tool(name="sync_echo", description="Echo back sync")
def sync_echo(msg: str) -> str:
    return f"echo:{msg}"

@mcp_tool(name="async_echo", description="Echo back async")
async def async_echo(msg: str) -> str:
    return f"async_echo:{msg}"

@pytest.fixture(autouse=True)
def patch_server(monkeypatch):
    import chuk_mcp_runtime.server.server as server_mod
    # Replace the real Server with FakeServer
    monkeypatch.setattr(server_mod, "Server", FakeServer)
    # Replace stdio_server
    monkeypatch.setattr(server_mod, "stdio_server", dummy_stdio)
    yield
    created_servers.clear()

# Helper function to safely run async code in tests
def run_async(coro):
    """Run an async coroutine in tests safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    return loop.run_until_complete(coro)

def test_list_and_call_tool():
    # Build server with stdio type
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)
    # Inject our dummy tools
    srv.tools_registry = {
        "sync_echo": sync_echo,
        "async_echo": async_echo
    }

    # Run serve() to register handlers
    run_async(srv.serve())

    # Grab the FakeServer instance and its handlers
    fake = created_servers[-1]
    handlers = fake.handlers

    # Test list_tools handler
    tool_list = run_async(handlers['list_tools']())
    names = {tool.name for tool in tool_list}
    assert names == {"sync_echo", "async_echo"}

    # Test call_tool for sync function
    result = run_async(handlers['call_tool']("sync_echo", {"msg": "hello"}))
    assert len(result) == 1
    assert result[0].text == "echo:hello"

    # Test call_tool for async function
    result2 = run_async(handlers['call_tool']("async_echo", {"msg": "world"}))
    assert len(result2) == 1
    assert result2[0].text == "async_echo:world"

def test_call_tool_errors():
    # Server with no tools registered
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)
    srv.tools_registry = {}

    # Run serve() to bind handlers
    run_async(srv.serve())
    fake = created_servers[-1]
    handlers = fake.handlers

    # Calling unknown tool should raise ValueError
    with pytest.raises(ValueError):
        run_async(handlers['call_tool']("does_not_exist", {}))