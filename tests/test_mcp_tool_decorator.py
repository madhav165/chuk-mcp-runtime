import inspect
import pytest
import asyncio

from chuk_mcp_runtime.common.mcp_tool_decorator import (
    mcp_tool,
    execute_tool_async,
    execute_tool,
    TOOLS_REGISTRY
)

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

# --- Test tools ---

@mcp_tool(name="add_sync", description="Add two numbers (sync)")
def add_sync(x: int, y: int) -> int:
    """Add two numbers (sync version)"""
    return x + y

@mcp_tool(name="add_async", description="Add two numbers (async)")
async def add_async(x: int, y: int) -> int:
    """Add two numbers (async version)"""
    return x + y

# --- Tests ---

def test_sync_decorator():
    # Check metadata
    assert hasattr(add_sync, "_mcp_tool")
    tool = add_sync._mcp_tool
    assert tool.name == "add_sync"
    assert tool.description == "Add two numbers (sync)"
    
    # Check registry
    assert "add_sync" in TOOLS_REGISTRY
    assert TOOLS_REGISTRY["add_sync"] is add_sync
    
    # Check schema
    assert "properties" in tool.inputSchema
    assert "x" in tool.inputSchema["properties"]
    assert "y" in tool.inputSchema["properties"]
    assert tool.inputSchema["properties"]["x"]["type"] == "integer"
    assert tool.inputSchema["properties"]["y"]["type"] == "integer"

def test_async_decorator():
    # Check metadata
    assert hasattr(add_async, "_mcp_tool")
    tool = add_async._mcp_tool
    assert tool.name == "add_async"
    assert tool.description == "Add two numbers (async)"
    
    # Check registry
    assert "add_async" in TOOLS_REGISTRY
    assert TOOLS_REGISTRY["add_async"] is add_async

@pytest.mark.asyncio
async def test_sync_function_is_async_wrapper():
    # The sync function should now be an async wrapper
    assert inspect.iscoroutinefunction(add_sync)
    result = await add_sync(2, 3)
    assert result == 5

def test_sync_helper_for_sync_function():
    # The sync helper should also return the correct sum
    result = add_sync.sync(4, 6)
    assert result == 10

@pytest.mark.asyncio
async def test_async_function():
    # The async function should behave normally
    assert inspect.iscoroutinefunction(add_async)
    result = await add_async(5, 7)
    assert result == 12

def test_sync_helper_for_async_function():
    # Even though add_async is async, .sync should block and return
    result = add_async.sync(8, 9)
    assert result == 17

@pytest.mark.asyncio
async def test_execute_tool_async():
    # Using the async executor works for both tools
    r1 = await execute_tool_async("add_sync", x=10, y=20)
    assert r1 == 30
    r2 = await execute_tool_async("add_async", x=3, y=4)
    assert r2 == 7

def test_execute_tool_sync():
    # Using the sync executor works for both tools
    r1 = execute_tool("add_sync", x=1, y=2)
    assert r1 == 3
    r2 = execute_tool("add_async", x=6, y=7)
    assert r2 == 13

def test_unregistered_tool():
    # Should raise KeyError for unknown tools
    with pytest.raises(KeyError):
        execute_tool("unknown", x=1)
    
    with pytest.raises(KeyError):
        run_async(execute_tool_async("unknown", x=1))