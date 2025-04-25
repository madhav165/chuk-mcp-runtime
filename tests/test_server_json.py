import pytest
import asyncio
import json
from contextlib import asynccontextmanager

from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool

# --- Fake Server and stdio_server stub ---

created_servers = []

class FakeServer:
    def __init__(self, name):
        created_servers.append(self)
        self.name = name
        self.handlers = {}

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

    def create_initialization_options(self):
        return {}

    async def run(self, read, write, options):
        # do nothing
        return

@asynccontextmanager
async def dummy_stdio():
    yield (None, None)

# --- Patch out real Server and stdio_server ---

@pytest.fixture(autouse=True)
def patch_server(monkeypatch):
    import chuk_mcp_runtime.server.server as server_mod
    monkeypatch.setattr(server_mod, "Server", FakeServer)
    monkeypatch.setattr(server_mod, "stdio_server", dummy_stdio)
    yield
    created_servers.clear()

# --- Define tools to test JSON serialization ---

@mcp_tool(name="dict_tool", description="Returns a dict")
def dict_tool() -> dict:
    return {"alpha": 1, "beta": [2, 3], "gamma": {"nested": True}}

@mcp_tool(name="list_tool", description="Returns a list")
async def list_tool() -> list:
    return ["a", "b", {"c": 3}]

def test_json_serialization_and_no_coroutine_errors():
    # Prepare server
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)
    # Inject our JSON-returning tools
    srv.tools_registry = {
        "dict_tool": dict_tool,
        "list_tool": list_tool
    }

    # Run serve() to register handlers
    asyncio.get_event_loop().run_until_complete(srv.serve())

    fake = created_servers[-1]
    call = fake.handlers['call_tool']

    # Test dict_tool
    result = asyncio.get_event_loop().run_until_complete(call("dict_tool", {}))
    assert len(result) == 1
    tc = result[0]
    # The TextContent.text should be pretty-printed JSON
    parsed = json.loads(tc.text)
    assert parsed == {"alpha": 1, "beta": [2, 3], "gamma": {"nested": True}}

    # Test list_tool
    result2 = asyncio.get_event_loop().run_until_complete(call("list_tool", {}))
    assert len(result2) == 1
    tc2 = result2[0]
    parsed2 = json.loads(tc2.text)
    assert parsed2 == ["a", "b", {"c": 3}]
