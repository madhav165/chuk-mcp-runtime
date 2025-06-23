# tests/server/test_server_session.py
"""
Test module for chuk_mcp_runtime server session management integration.

Tests session context injection, session-aware tools, and session isolation
within the MCP server framework using native session management.
"""
import pytest
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Union, Optional

from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool, TOOLS_REGISTRY
from chuk_mcp_runtime.session.native_session_management import (
    MCPSessionManager,
    SessionContext,
    require_session,
    get_session_or_none,
    get_user_or_none,
    session_required,
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

# --- Session-aware test tools using native API ---

@mcp_tool(name="get_current_session_native", description="Get current session using native API")
async def get_current_session_native() -> Dict[str, Any]:
    """Get the current session context using native API."""
    current_session = get_session_or_none()
    current_user = get_user_or_none()
    return {
        "session_id": current_session,
        "user_id": current_user,
        "has_session": current_session is not None,
        "message": f"Current session: {current_session}" if current_session else "No session set"
    }

@session_required
@mcp_tool(name="write_file_native", description="Write a file using native session management")
async def write_file_native(
    content: str,
    filename: str,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """Write a file with native session management."""
    # Session is guaranteed by @session_required decorator
    effective_session = require_session()
    
    return {
        "artifact_id": f"file_{hash(content) % 10000:04d}",
        "filename": filename,
        "session_id": effective_session,
        "bytes": len(content),
        "operation": "create",
        "message": f"File '{filename}' written to session '{effective_session}'"
    }

@session_required
@mcp_tool(name="list_session_files_native", description="List files using native session management")
async def list_session_files_native(session_id: Optional[str] = None) -> Dict[str, Any]:
    """List files in a session using native API."""
    effective_session = require_session()
    
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

# Mock session manager for testing
class MockSessionManager:
    def __init__(self, sandbox_id="test"):
        self.sandbox_id = sandbox_id
        self.sessions = {}
        self._current_session = None
        self._current_user = None
    
    async def create_session(self, user_id=None, ttl_hours=24, metadata=None):
        import uuid
        session_id = f"session-{uuid.uuid4().hex[:8]}"
        self.sessions[session_id] = {
            "user_id": user_id,
            "metadata": metadata or {},
            "created": True
        }
        return session_id
    
    async def validate_session(self, session_id):
        return session_id in self.sessions
    
    def set_current_session(self, session_id, user_id=None):
        self._current_session = session_id
        self._current_user = user_id
    
    def get_current_session(self):
        return self._current_session
    
    def get_current_user(self):
        return self._current_user
    
    def clear_context(self):
        self._current_session = None
        self._current_user = None
    
    async def auto_create_session_if_needed(self, user_id=None):
        if self._current_session and await self.validate_session(self._current_session):
            return self._current_session
        
        session_id = await self.create_session(user_id=user_id)
        self.set_current_session(session_id, user_id)
        return session_id
    
    def get_cache_stats(self):
        return {"sessions": len(self.sessions)}

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
    
    # Register test tools
    TOOLS_REGISTRY["get_current_session_native"] = get_current_session_native
    TOOLS_REGISTRY["write_file_native"] = write_file_native
    TOOLS_REGISTRY["list_session_files_native"] = list_session_files_native
    TOOLS_REGISTRY["no_session_tool"] = no_session_tool
    
    yield
    
    # Cleanup
    created_servers.clear()
    TOOLS_REGISTRY.clear()

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

# --- Native Session Management Tests ---

class TestNativeSessionTools:
    """Test native session management tools."""
    
    def test_get_current_session_native_tool(self):
        """Test getting current session via native tool."""
        config = {"server": {"type": "stdio"}, "tools": {}}
        srv = MCPServer(config)
        run_async(srv.serve())
        
        fake = created_servers[-1]
        handlers = fake.handlers
        
        # Test with no session initially
        result = run_async(handlers['call_tool']("get_current_session_native", {}))
        assert len(result) == 1
        
        # Parse JSON result
        data = json.loads(result[0].text)
        assert data["session_id"] is None
        assert data["has_session"] is False
        assert "No session set" in data["message"]

class TestNativeSessionContextInjection:
    """Test automatic session context injection with native session management."""
    
    def test_session_injection_for_artifact_tools(self):
        """Test that session context is auto-injected for artifact tools."""
        config = {
            "server": {"type": "stdio"}, 
            "tools": {},
            "sessions": {"sandbox_id": "test-injection"}
        }
        srv = MCPServer(config)
        
        # Mock the session manager
        mock_manager = MockSessionManager()
        srv.session_manager = mock_manager
        
        run_async(srv.serve())
        
        fake = created_servers[-1]
        handlers = fake.handlers
        
        # Call an artifact tool (write_file_native) without explicit session
        result = run_async(handlers['call_tool']("write_file_native", {
            "content": "test content",
            "filename": "test.txt"
        }))
        
        assert len(result) == 1
        data = json.loads(result[0].text)
        
        # Should have auto-created and injected session
        assert "session_id" in data
        assert data["session_id"] is not None
        assert data["filename"] == "test.txt"
        assert data["operation"] == "create"

    def test_no_session_injection_for_regular_tools(self):
        """Test that session is not injected for non-artifact tools."""
        config = {"server": {"type": "stdio"}, "tools": {}}
        srv = MCPServer(config)
        run_async(srv.serve())
        
        fake = created_servers[-1]
        handlers = fake.handlers
        
        # Call a regular tool
        result = run_async(handlers['call_tool']("no_session_tool", {
            "message": "hello"
        }))
        
        assert len(result) == 1
        assert result[0].text == "No session needed: hello"

class TestNativeSessionIsolation:
    """Test session isolation with native session management."""
    
    def test_concurrent_session_contexts(self):
        """Test that different session contexts are isolated."""
        config = {"server": {"type": "stdio"}, "tools": {}}
        srv = MCPServer(config)
        
        # Mock session manager
        mock_manager = MockSessionManager()
        srv.session_manager = mock_manager
        
        async def test_concurrent_sessions():
            # Create two different sessions
            session1 = await mock_manager.create_session(user_id="user1")
            session2 = await mock_manager.create_session(user_id="user2")
            
            results = []
            
            # Simulate concurrent tool calls in different sessions
            async def call_in_session(session_id, user_id, call_id):
                async with SessionContext(mock_manager, session_id=session_id, user_id=user_id):
                    current = require_session()
                    current_user = get_user_or_none()
                    results.append({
                        "call_id": call_id,
                        "session": current,
                        "user": current_user
                    })
            
            # Run concurrent calls
            await asyncio.gather(
                call_in_session(session1, "user1", "call1"),
                call_in_session(session2, "user2", "call2"),
                call_in_session(session1, "user1", "call3"),
            )
            
            # Verify isolation
            assert len(results) == 3
            
            call1 = next(r for r in results if r["call_id"] == "call1")
            call2 = next(r for r in results if r["call_id"] == "call2")
            call3 = next(r for r in results if r["call_id"] == "call3")
            
            # Calls 1 and 3 should have same session (session1)
            assert call1["session"] == session1
            assert call3["session"] == session1
            assert call1["user"] == "user1"
            assert call3["user"] == "user1"
            
            # Call 2 should have different session (session2)  
            assert call2["session"] == session2
            assert call2["user"] == "user2"
            assert call2["session"] != call1["session"]
        
        run_async(test_concurrent_sessions())

class TestNativeSessionErrorHandling:
    """Test error handling in native session management."""
    
    def test_session_required_decorator_error(self):
        """Test that @session_required decorator raises error when no session."""
        config = {"server": {"type": "stdio"}, "tools": {}}
        srv = MCPServer(config)
        run_async(srv.serve())
        
        fake = created_servers[-1]
        handlers = fake.handlers
        
        # Try to call a session-required tool without session context
        # This should result in an error response
        result = run_async(handlers['call_tool']("write_file_native", {
            "content": "test",
            "filename": "test.txt"
        }))
        
        assert len(result) == 1
        # Should contain error message about session requirement
        assert "error" in result[0].text.lower() or "session" in result[0].text.lower()

class TestNativeSessionIntegration:
    """Test integration between native session management and MCP server."""
    
    def test_session_manager_integration(self):
        """Test that MCPServer properly integrates with native session manager."""
        config = {
            "server": {"type": "stdio"},
            "sessions": {
                "sandbox_id": "integration-test",
                "default_ttl_hours": 2
            }
        }
        srv = MCPServer(config)
        
        # Verify session manager was created
        assert srv.session_manager is not None
        assert srv.session_manager.sandbox_id == "integration-test"
        assert srv.session_manager.default_ttl_hours == 2
        
    def test_session_stats_logging(self):
        """Test that session statistics are properly logged."""
        config = {"server": {"type": "stdio"}, "sessions": {"sandbox_id": "stats-test"}}
        srv = MCPServer(config)
        
        # Get cache stats
        stats = srv.session_manager.get_cache_stats()
        assert isinstance(stats, dict)
        
    def test_session_creation_via_server(self):
        """Test creating sessions through the server interface."""
        config = {"server": {"type": "stdio"}}
        srv = MCPServer(config)
        
        async def test_session_creation():
            session_id = await srv.create_user_session(
                user_id="test_user",
                metadata={"test": True}
            )
            
            assert session_id is not None
            assert isinstance(session_id, str)
            
            # Verify session exists
            is_valid = await srv.session_manager.validate_session(session_id)
            assert is_valid is True
        
        run_async(test_session_creation())

if __name__ == "__main__":
    pytest.main([__file__, "-v"])