# tests/test_mcp_tool_decorator.py
import pytest
import inspect
from chuk_mcp_runtime.common.mcp_tool_decorator import (
    mcp_tool,
    TOOLS_REGISTRY,
    execute_tool_async,
    execute_tool,
)

# --- Define two tools, one sync and one async ---

@mcp_tool(name="add_sync", description="Add two numbers (sync)")
def add_sync(x: int, y: int) -> int:
    return x + y

@mcp_tool(name="add_async", description="Add two numbers (async)")
async def add_async(x: int, y: int) -> int:
    return x + y

# --- Tests ---

def test_tools_registered():
    # Both tools should be in the global registry
    assert "add_sync" in TOOLS_REGISTRY
    assert "add_async" in TOOLS_REGISTRY

    # Metadata attached correctly
    meta_sync = add_sync._mcp_tool
    assert meta_sync.name == "add_sync"
    assert "Add two numbers (sync)" in meta_sync.description

    meta_async = add_async._mcp_tool
    assert meta_async.name == "add_async"
    assert "Add two numbers (async)" in meta_async.description

@pytest.mark.asyncio
async def test_async_wrapper_on_sync_function():
    # The decorator makes add_sync an async function
    assert inspect.iscoroutinefunction(add_sync)

    # Awaiting it returns the correct sum
    result = await add_sync(2, 3)
    assert result == 5

def test_sync_helper_for_sync_function():
    # The sync helper should also return the correct sum
    result = add_sync.sync(4, 6)
    assert result == 10

@pytest.mark.asyncio
async def test_async_wrapper_on_async_function():
    # add_async remains async
    assert inspect.iscoroutinefunction(add_async)

    # Awaiting it returns the correct sum
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
