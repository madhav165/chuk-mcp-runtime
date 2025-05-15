# tests/test_server.py
"""
Test module for chuk_mcp_runtime server with tool naming compatibility.

Tests both synchronous and asynchronous tool execution with various
naming conventions (dot vs underscore notation).
"""
import pytest
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Union

from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool, TOOLS_REGISTRY
from chuk_mcp_runtime.common.tool_naming import resolve_tool_name, update_naming_maps

# --- Setup fake Server and stdio_server ---

created_servers = []

class FakeTextContent:
    """Mock TextContent for testing."""
    def __init__(self, type="text", text=""):
        self.type = type
        self.text = text

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
async def sync_echo(msg: str) -> str:
    return f"echo:{msg}"

@mcp_tool(name="async_echo", description="Echo back async")
async def async_echo(msg: str) -> str:
    return f"async_echo:{msg}"

@mcp_tool(name="wikipedia.search", description="Search Wikipedia")
async def wikipedia_search(query: str, limit: int = 5) -> List[Dict[str, str]]:
    return [{"title": f"Result for {query}", "url": f"https://en.wikipedia.org/{query}"}]

@mcp_tool(name="duckduckgo_search", description="Search DuckDuckGo")
async def duckduckgo_search(query: str, max_results: int = 5, snippet_words: int = 250) -> List[Dict[str, str]]:
    return [{"title": f"DDG Result for {query}", "url": f"https://duckduckgo.com/{query}"}]

@mcp_tool(name="proxy.google.search", description="Search Google")
async def google_search(query: str, max_results: int = 5, snippet_words: int = 250) -> List[Dict[str, str]]:
    return [{"title": f"Google Result for {query}", "url": f"https://google.com/search?q={query}"}]

@pytest.fixture(autouse=True)
def patch_server(monkeypatch):
    import chuk_mcp_runtime.server.server as server_mod
    # Patch mcp.types.TextContent with our fake for easier testing
    monkeypatch.setattr(server_mod, "TextContent", FakeTextContent)
    # Replace the real Server with FakeServer
    monkeypatch.setattr(server_mod, "Server", FakeServer)
    # Replace stdio_server
    monkeypatch.setattr(server_mod, "stdio_server", dummy_stdio)
    # Clear the tools registry before each test
    TOOLS_REGISTRY.clear()
    # Register our test tools
    TOOLS_REGISTRY["sync_echo"] = sync_echo
    TOOLS_REGISTRY["async_echo"] = async_echo
    TOOLS_REGISTRY["wikipedia.search"] = wikipedia_search
    TOOLS_REGISTRY["duckduckgo_search"] = duckduckgo_search
    TOOLS_REGISTRY["proxy.google.search"] = google_search
    # Update the naming maps
    update_naming_maps()
    
    yield
    # Clean up
    created_servers.clear()
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

def test_list_tools():
    """Test listing tools works correctly."""
    # Build server with stdio type
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)
    
    # Run serve() to register handlers
    run_async(srv.serve())

    # Grab the FakeServer instance and its handlers
    fake = created_servers[-1]
    handlers = fake.handlers

    # Test list_tools handler
    tool_list = run_async(handlers['list_tools']())
    names = {tool.name for tool in tool_list}
    
    # Should include all tools we registered
    assert "sync_echo" in names
    assert "async_echo" in names
    assert "wikipedia.search" in names
    assert "duckduckgo_search" in names
    assert "proxy.google.search" in names

def test_call_tool_basic():
    """Test basic tool calling functionality."""
    # Build server with stdio type
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)

    # Run serve() to register handlers
    run_async(srv.serve())

    # Grab the FakeServer instance and its handlers
    fake = created_servers[-1]
    handlers = fake.handlers

    # Test call_tool for sync function
    result = run_async(handlers['call_tool']("sync_echo", {"msg": "hello"}))
    assert len(result) == 1
    assert result[0].text == "echo:hello"

    # Test call_tool for async function
    result2 = run_async(handlers['call_tool']("async_echo", {"msg": "world"}))
    assert len(result2) == 1
    assert result2[0].text == "async_echo:world"

def test_call_tool_naming_compatibility():
    """Test tool naming compatibility with dot vs underscore notation."""
    # Build server with stdio type
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)

    # Run serve() to register handlers
    run_async(srv.serve())

    # Grab the FakeServer instance and its handlers
    fake = created_servers[-1]
    handlers = fake.handlers

    # Test calling with original dot notation
    result1 = run_async(handlers['call_tool']("wikipedia.search", {"query": "python"}))
    assert len(result1) == 1
    assert "Result for python" in result1[0].text
    
    # Test calling with underscore notation
    result2 = run_async(handlers['call_tool']("wikipedia_search", {"query": "python"}))
    assert len(result2) == 1
    assert "Result for python" in result2[0].text
    
    # Test calling a tool registered with underscore using dot notation
    result3 = run_async(handlers['call_tool']("duckduckgo.search", {"query": "python"}))
    assert len(result3) == 1
    assert "DDG Result for python" in result3[0].text
    
    # Test calling tool with nested proxy namespace
    result4 = run_async(handlers['call_tool']("google.search", {"query": "python"}))
    assert len(result4) == 1
    assert "Google Result for python" in result4[0].text
    
    # Test with full proxy namespace
    result5 = run_async(handlers['call_tool']("proxy.google.search", {"query": "python"}))
    assert len(result5) == 1
    assert "Google Result for python" in result5[0].text

def test_tool_resolution():
    """Test the tool name resolution function directly."""
    # Test resolving dot to underscore
    assert resolve_tool_name("wikipedia.search") in ["wikipedia.search", "wikipedia_search"]
    
    # Test resolving underscore to dot
    assert resolve_tool_name("duckduckgo_search") in ["duckduckgo.search", "duckduckgo_search"]
    
    # Test resolving with proxy prefix
    assert resolve_tool_name("google.search") in ["proxy.google.search", "google_search"]
    
    # Test resolving unknown name (should return original)
    assert resolve_tool_name("unknown.tool") == "unknown.tool"

def test_call_tool_errors():
    """Test error handling in tool calling."""
    # Server with registry but missing tool
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)

    # Run serve() to bind handlers
    run_async(srv.serve())
    fake = created_servers[-1]
    handlers = fake.handlers

    # Calling unknown tool should raise ValueError
    with pytest.raises(ValueError):
        run_async(handlers['call_tool']("does_not_exist", {}))

def test_dynamic_tool_registration():
    """Test registering tools dynamically and ensuring naming resolution works."""
    # Build server with stdio type
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)

    # Run serve() to register handlers
    run_async(srv.serve())

    # Grab the FakeServer instance and its handlers
    fake = created_servers[-1]
    handlers = fake.handlers
    
    # Define a new tool
    @mcp_tool(name="new.dynamic.tool", description="Dynamic test tool")
    async def dynamic_tool(param: str) -> str:
        return f"dynamic:{param}"
    
    # Register it
    run_async(srv.register_tool("new.dynamic.tool", dynamic_tool))
    
    # Should be callable with original name
    result1 = run_async(handlers['call_tool']("new.dynamic.tool", {"param": "test"}))
    assert len(result1) == 1
    assert result1[0].text == "dynamic:test"
    
    # Should be callable with underscore notation
    result2 = run_async(handlers['call_tool']("new_dynamic_tool", {"param": "test2"}))
    assert len(result2) == 1
    assert result2[0].text == "dynamic:test2"
    
    # Should be callable with partial name
    result3 = run_async(handlers['call_tool']("dynamic.tool", {"param": "test3"}))
    assert len(result3) == 1
    assert result3[0].text == "dynamic:test3"

def test_openai_mode_compatibility():
    """Test compatibility with OpenAI mode naming conventions."""
    # Add additional OpenAI-style tools to registry
    TOOLS_REGISTRY["reddit_search"] = async_echo  # Just reuse echo for testing
    update_naming_maps()  # Make sure maps are updated
    
    # Build server with stdio type
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)

    # Run serve() to register handlers
    run_async(srv.serve())

    # Grab the FakeServer instance and its handlers
    fake = created_servers[-1]
    handlers = fake.handlers
    
    # Test calling with underscore style (OpenAI compatible)
    result1 = run_async(handlers['call_tool']("reddit_search", {"msg": "test"}))
    assert len(result1) == 1
    assert "async_echo:test" in result1[0].text
    
    # Test calling with dot style
    result2 = run_async(handlers['call_tool']("reddit.search", {"msg": "test2"}))
    assert len(result2) == 1
    assert "async_echo:test2" in result2[0].text

def test_return_types():
    """Test different return types from tools."""
    # Define test tools with different return types
    @mcp_tool(name="return.string", description="Return string")
    async def return_string() -> str:
        return "simple string"
    
    @mcp_tool(name="return.dict", description="Return dictionary")
    async def return_dict() -> Dict[str, Any]:
        return {"key": "value", "nested": {"inner": "data"}}
    
    @mcp_tool(name="return.list", description="Return list")
    async def return_list() -> List[Any]:
        return [1, 2, 3, {"item": "value"}]
    
    # Add to registry
    TOOLS_REGISTRY["return.string"] = return_string
    TOOLS_REGISTRY["return.dict"] = return_dict
    TOOLS_REGISTRY["return.list"] = return_list
    update_naming_maps()
    
    # Build server with stdio type
    config = {"server": {"type": "stdio"}, "tools": {}}
    srv = MCPServer(config)

    # Run serve() to register handlers
    run_async(srv.serve())

    # Grab the FakeServer instance and its handlers
    fake = created_servers[-1]
    handlers = fake.handlers
    
    # Test string return
    result1 = run_async(handlers['call_tool']("return.string", {}))
    assert len(result1) == 1
    assert result1[0].text == "simple string"
    
    # Test dict return (should be JSON)
    result2 = run_async(handlers['call_tool']("return.dict", {}))
    assert len(result2) == 1
    assert '"key": "value"' in result2[0].text
    assert '"nested"' in result2[0].text
    
    # Test list return (should be JSON)
    result3 = run_async(handlers['call_tool']("return.list", {}))
    assert len(result3) == 1
    # The JSON may be formatted with newlines and spaces
    assert '1' in result3[0].text
    assert '2' in result3[0].text
    assert '3' in result3[0].text
    assert '"item": "value"' in result3[0].text
    
    # Test with underscore notation
    result4 = run_async(handlers['call_tool']("return_dict", {}))
    assert len(result4) == 1
    assert '"key": "value"' in result4[0].text

if __name__ == "__main__":
    test_list_tools()
    test_call_tool_basic()
    test_call_tool_naming_compatibility()
    test_tool_resolution()
    test_call_tool_errors()
    test_dynamic_tool_registration()
    test_openai_mode_compatibility()
    test_return_types()
    print("All tests passed!")