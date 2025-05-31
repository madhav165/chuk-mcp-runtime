# tests/test_server_session.py
"""
Test module for chuk_mcp_runtime server session management integration.

Tests session context injection, session-aware tools, and session isolation
within the MCP server framework.
"""
import pytest
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Union, Optional

from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool, TOOLS_REGISTRY
from chuk_mcp_runtime.session.session_management import (
    set_session_context, 
    get_session_context, 
    clear_session_context,
    validate_session_parameter,
    normalize_session_id,
    SessionError
)

# --- Setup fake Server and stdio_server for testing ---

created_servers = []

class FakeTextContent:
    """Mock TextContent for testing."""
    def __init__(self, type="text", text=""):
        self.type = type
        self.text = text

class FakeServer:
    def __init__(self, name):
        created_servers.append(self)
        self.name = name
        self.handlers = {}
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

    async def run(self, read, write, options):
        return

@asynccontextmanager
async def dummy_stdio():
    yield (None, None)

# --- Session-aware test tools ---

@mcp_tool(name="set_session", description="Set session context")
async def set_session(session_id: str) -> Dict[str, Any]:
    """Set the current session context."""
    # Normalize the session ID before setting
    normalized_session = normalize_session_id(session_id)
    set_session_context(normalized_session)
    return {
        "success": True,
        "session_id": normalized_session,  # Return normalized version
        "message": f"Session context set to: {normalized_session}"
    }

@mcp_tool(name="get_current_session", description="Get current session")
async def get_current_session() -> Dict[str, Any]:
    """Get the current session context."""
    current_session = get_session_context()
    return {
        "session_id": current_session,
        "has_session": current_session is not None,
        "message": f"Current session: {current_session}" if current_session else "No session set"
    }

@mcp_tool(name="write_file", description="Write a file (requires session)")
async def write_file(
    content: str,
    filename: str,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """Write a file with session validation."""
    # Use session validation
    effective_session = validate_session_parameter(session_id, "write_file")
    
    return {
        "artifact_id": f"file_{hash(content) % 10000:04d}",
        "filename": filename,
        "session_id": effective_session,
        "bytes": len(content),
        "operation": "create",
        "message": f"File '{filename}' written to session '{effective_session}'"
    }

@mcp_tool(name="list_session_files", description="List files in session")
async def list_session_files(session_id: Optional[str] = None) -> Dict[str, Any]:
    """List files in a session."""
    effective_session = validate_session_parameter(session_id, "list_session_files")
    
    # Mock file list for testing
    mock_files = [
        {"filename": f"file1_{effective_session}.txt", "session_id": effective_session},
        {"filename": f"file2_{effective_session}.txt", "session_id": effective_session},
    ]
    
    return {
        "count": len(mock_files),
        "session_id": effective_session,
        "files": mock_files
    }

@mcp_tool(name="no_session_tool", description="Tool that doesn't need session")
async def no_session_tool(message: str) -> str:
    """A tool that doesn't require session context."""
    return f"No session needed: {message}"

# --- Test fixtures ---

@pytest.fixture(autouse=True)
def patch_server_session(monkeypatch):
    """Patch server components for session testing."""
    import chuk_mcp_runtime.server.server as server_mod
    
    # Patch mcp components
    monkeypatch.setattr(server_mod, "TextContent", FakeTextContent)
    monkeypatch.setattr(server_mod, "Server", FakeServer)
    monkeypatch.setattr(server_mod, "stdio_server", dummy_stdio)
    
    # Clear state
    TOOLS_REGISTRY.clear()
    clear_session_context()
    
    # Register test tools
    TOOLS_REGISTRY["set_session"] = set_session
    TOOLS_REGISTRY["get_current_session"] = get_current_session
    TOOLS_REGISTRY["write_file"] = write_file
    TOOLS_REGISTRY["list_session_files"] = list_session_files
    TOOLS_REGISTRY["no_session_tool"] = no_session_tool
    
    yield
    
    # Cleanup
    created_servers.clear()
    TOOLS_REGISTRY.clear()
    clear_session_context()

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

# --- Session Management Tests ---

class TestBasicSessionTools:
    """Test basic session management tools."""
    
    def test_set_session_tool(self):
        """Test setting session via tool."""
        config = {"server": {"type": "stdio"}, "tools": {}}
        srv = MCPServer(config)
        run_async(srv.serve())
        
        fake = created_servers[-1]
        handlers = fake.handlers
        
        # Set session via tool
        result = run_async(handlers['call_tool']("set_session", {"session_id": "test123"}))
        assert len(result) == 1
        
        # Parse JSON result
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["session_id"] == "test123"
        assert "Session context set to: test123" in data["message"]
    
    def test_get_current_session_tool(self):
        """Test getting current session via tool."""
        config = {"server": {"type": "stdio"}, "tools": {}}
        srv = MCPServer(config)
        run_async(srv.serve())
        
        fake = created_servers[-1]
        handlers = fake.handlers
        
        # No session initially
        result1 = run_async(handlers['call_tool']("get_current_session", {}))
        data1 = json.loads(result1[0].text)
        assert data1["session_id"] is None
        assert data1["has_session"] is False
        
        # Set session
        run_async(handlers['call_tool']("set_session", {"session_id": "active123"}))
        
        # Get session again
        result2 = run_async(handlers['call_tool']("get_current_session", {}))
        data2 = json.loads(result2[0].text)
        assert data2["session_id"] == "active123"
        assert data2["has_session"] is True


class TestSessionContextInjection:
    """Test automatic session context injection."""
    
    def test_session_injection_for_session_aware_tools(self):
        """Test that session context is injected for session-aware tools."""
        config = {"server": {"type": "stdio"}, "tools": {}}
        srv = MCPServer(config)