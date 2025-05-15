# tests/test_server_json.py
"""
Test module for JSON serialization and tool calling with naming compatibility.

Tests how different types of tool return values are serialized
and how tool names with different formats are resolved.
"""
import pytest
import asyncio
import json
from contextlib import asynccontextmanager

from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool, TOOLS_REGISTRY
from chuk_mcp_runtime.common.tool_naming import update_naming_maps
from mcp.types import TextContent  # import only TextContent for passthrough

# Capture FakeServer instances
_created = []

class FakeServer:
    def __init__(self, name):
        _created.append(self)
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
    # Clear TOOLS_REGISTRY before each test
    TOOLS_REGISTRY.clear()
    yield
    _created.clear()
    TOOLS_REGISTRY.clear()

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

# --- JSON‐serializable tools ---

@mcp_tool(name="dict_tool", description="Returns a dict")
async def dict_tool() -> dict:
    return {"a": 1, "b": [2, 3], "c": {"x": True}}

@mcp_tool(name="list.tool", description="Returns a list")
async def list_tool() -> list:
    return ["hello", {"num": 5}, False]

# --- Extended tools ---

@mcp_tool(name="string.tool", description="Returns a plain string")
async def string_tool() -> str:
    return "plain text"

@mcp_tool(name="wrapped_tool", description="Returns pre‐wrapped TextContent")
async def wrapped_tool() -> list:
    # Only TextContent, to keep instantiation simple
    return [
        TextContent(type="text", text="already text 1"),
        TextContent(type="text", text="already text 2"),
    ]

@mcp_tool(name="error_tool", description="Raises an error")
async def error_tool():
    raise RuntimeError("oh no")

# --- Tools with different naming conventions ---

@mcp_tool(name="example.dot.notation", description="Tool with dot notation")
async def dot_notation_tool() -> dict:
    return {"format": "dot.notation", "value": 42}

@mcp_tool(name="example_underscore_notation", description="Tool with underscore notation")
async def underscore_notation_tool() -> dict:
    return {"format": "underscore_notation", "value": 43}

@mcp_tool(name="proxy.example.nested", description="Tool with proxy namespace")
async def proxy_nested_tool() -> dict:
    return {"format": "proxy.nested", "value": 44}

def test_json_serialization_and_awaiting():
    """Test basic JSON serialization for different tool return types."""
    # 1) Build server
    cfg = {"server": {"type": "stdio"}, "tools": {}}
    server = MCPServer(cfg)

    # 2) Register tools in registry
    TOOLS_REGISTRY["dict_tool"] = dict_tool
    TOOLS_REGISTRY["list.tool"] = list_tool
    TOOLS_REGISTRY["string.tool"] = string_tool
    TOOLS_REGISTRY["wrapped_tool"] = wrapped_tool
    TOOLS_REGISTRY["error_tool"] = error_tool

    # 3) Register handlers
    run_async(server.serve())

    fake = _created[-1]
    call = fake.handlers['call_tool']

    # -- dict_tool --
    out = run_async(call("dict_tool", {}))
    assert len(out) == 1
    parsed = json.loads(out[0].text)
    assert parsed == {"a": 1, "b": [2, 3], "c": {"x": True}}

    # -- list_tool --
    out2 = run_async(call("list.tool", {}))
    assert len(out2) == 1
    parsed2 = json.loads(out2[0].text)
    assert parsed2 == ["hello", {"num": 5}, False]

    # -- string_tool --
    out3 = run_async(call("string.tool", {}))
    assert len(out3) == 1
    assert out3[0].text == "plain text"

    # -- wrapped_tool --
    out4 = run_async(call("wrapped_tool", {}))
    assert len(out4) == 2
    assert out4[0].text == "already text 1"
    assert out4[1].text == "already text 2"

    # -- error_tool --
    with pytest.raises(ValueError) as ei:
        run_async(call("error_tool", {}))
    assert "oh no" in str(ei.value)

def test_naming_compatibility():
    """Test tool calling with different naming conventions."""
    # 1) Build server
    cfg = {"server": {"type": "stdio"}, "tools": {}}
    server = MCPServer(cfg)

    # 2) Register tools in registry
    TOOLS_REGISTRY["dict_tool"] = dict_tool
    TOOLS_REGISTRY["list.tool"] = list_tool
    TOOLS_REGISTRY["example.dot.notation"] = dot_notation_tool
    TOOLS_REGISTRY["example_underscore_notation"] = underscore_notation_tool
    TOOLS_REGISTRY["proxy.example.nested"] = proxy_nested_tool
    
    # Update naming maps
    update_naming_maps()

    # 3) Register handlers
    run_async(server.serve())

    fake = _created[-1]
    call = fake.handlers['call_tool']

    # -- Call with original dot notation --
    out1 = run_async(call("list.tool", {}))
    assert len(out1) == 1
    parsed1 = json.loads(out1[0].text)
    assert parsed1 == ["hello", {"num": 5}, False]

    # -- Call with underscore notation --
    out2 = run_async(call("list_tool", {}))
    assert len(out2) == 1
    parsed2 = json.loads(out2[0].text)
    assert parsed2 == ["hello", {"num": 5}, False]
    
    # -- Call tool registered with dot notation using underscore --
    out3 = run_async(call("example_dot_notation", {}))
    assert len(out3) == 1
    parsed3 = json.loads(out3[0].text)
    assert parsed3["format"] == "dot.notation"
    
    # -- Call tool registered with underscore notation using dots --
    out4 = run_async(call("example.underscore.notation", {}))
    assert len(out4) == 1
    parsed4 = json.loads(out4[0].text)
    assert parsed4["format"] == "underscore_notation"
    
    # -- Call tool with proxy namespace using short form --
    out5 = run_async(call("example.nested", {}))
    assert len(out5) == 1
    parsed5 = json.loads(out5[0].text)
    assert parsed5["format"] == "proxy.nested"

def test_error_handling_with_naming_resolution():
    """Test error handling with tool naming resolution."""
    # 1) Build server
    cfg = {"server": {"type": "stdio"}, "tools": {}}
    server = MCPServer(cfg)

    # 2) Register tools in registry
    TOOLS_REGISTRY["error_tool"] = error_tool
    
    # Update naming maps
    update_naming_maps()

    # 3) Register handlers
    run_async(server.serve())

    fake = _created[-1]
    call = fake.handlers['call_tool']

    # -- Call error tool with original name --
    with pytest.raises(ValueError) as ei:
        run_async(call("error_tool", {}))
    assert "oh no" in str(ei.value)
    
    # -- Call nonexistent tool should raise clear error --
    with pytest.raises(ValueError) as ei:
        run_async(call("nonexistent_tool", {}))
    assert "Tool not found" in str(ei.value)
    
    # -- Call error tool with alternate naming --
    # First register it with a new name
    TOOLS_REGISTRY["error.tool"] = error_tool
    update_naming_maps()
    
    with pytest.raises(ValueError) as ei:
        run_async(call("error_tool", {}))
    assert "oh no" in str(ei.value)

if __name__ == "__main__":
    pytest.main(["-xvs", __file__])