# tests/test_server_json.py
import pytest
import asyncio
import json
from contextlib import asynccontextmanager

from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from mcp.types import TextContent  # import only TextContent for passthrough

# Capture FakeServer instances
_created = []

class FakeServer:
    def __init__(self, name):
        _created.append(self)
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

    async def run(self, read, write, opts):
        # no-op
        return

@asynccontextmanager
async def dummy_stdio():
    yield (None, None)

@pytest.fixture(autouse=True)
def patch_server(monkeypatch):
    import chuk_mcp_runtime.server.server as srv_mod
    monkeypatch.setattr(srv_mod, "Server", FakeServer)
    monkeypatch.setattr(srv_mod, "stdio_server", dummy_stdio)
    yield
    _created.clear()

# --- JSON‐serializable tools ---

@mcp_tool(name="dict_tool", description="Returns a dict")
def dict_tool() -> dict:
    return {"a": 1, "b": [2, 3], "c": {"x": True}}

@mcp_tool(name="list_tool", description="Returns a list")
async def list_tool() -> list:
    return ["hello", {"num": 5}, False]

# --- Extended tools ---

@mcp_tool(name="string_tool", description="Returns a plain string")
def string_tool() -> str:
    return "plain text"

@mcp_tool(name="wrapped_tool", description="Returns pre‐wrapped TextContent")
def wrapped_tool() -> list:
    # Only TextContent, to keep instantiation simple
    return [
        TextContent(type="text", text="already text 1"),
        TextContent(type="text", text="already text 2"),
    ]

@mcp_tool(name="error_tool", description="Raises an error")
def error_tool():
    raise RuntimeError("oh no")

def test_json_serialization_and_awaiting():
    # 1) Build server
    cfg = {"server": {"type": "stdio"}, "tools": {}}
    server = MCPServer(cfg)

    # 2) Inject tools
    server.tools_registry = {
        "dict_tool": dict_tool,
        "list_tool": list_tool,
        "string_tool": string_tool,
        "wrapped_tool": wrapped_tool,
        "error_tool": error_tool
    }

    # 3) Register handlers
    asyncio.get_event_loop().run_until_complete(server.serve())

    fake = _created[-1]
    call = fake.handlers['call_tool']

    # -- dict_tool --
    out = asyncio.get_event_loop().run_until_complete(call("dict_tool", {}))
    assert len(out) == 1
    parsed = json.loads(out[0].text)
    assert parsed == {"a": 1, "b": [2, 3], "c": {"x": True}}

    # -- list_tool --
    out2 = asyncio.get_event_loop().run_until_complete(call("list_tool", {}))
    assert len(out2) == 1
    parsed2 = json.loads(out2[0].text)
    assert parsed2 == ["hello", {"num": 5}, False]

    # -- string_tool --
    out3 = asyncio.get_event_loop().run_until_complete(call("string_tool", {}))
    assert len(out3) == 1
    assert out3[0].text == "plain text"

    # -- wrapped_tool --
    out4 = asyncio.get_event_loop().run_until_complete(call("wrapped_tool", {}))
    assert len(out4) == 2
    assert out4[0].text == "already text 1"
    assert out4[1].text == "already text 2"

    # -- error_tool --
    with pytest.raises(ValueError) as ei:
        asyncio.get_event_loop().run_until_complete(call("error_tool", {}))
    assert "oh no" in str(ei.value)
