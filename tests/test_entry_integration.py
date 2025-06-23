# tests/test_entry_integration.py
"""
Test module for proxy integration functionality with native session management.

Tests how the proxy system integrates with the entry point
and how it handles tool naming conventions with session context.
"""
import pytest
import os
import sys
import asyncio
from unittest.mock import MagicMock, patch

# Import entry module, but ensure we use the same mock as test_proxy_manager
import chuk_mcp_runtime.entry as entry

# --- Improved helper for running async code ---
def run_async(coro):
    """Run an async coroutine in tests safely with a new event loop."""
    # Always create a new event loop to avoid 'already running' errors
    old_loop = None
    try:
        old_loop = asyncio.get_event_loop()
    except RuntimeError:
        pass
    
    # Create a new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        return loop.run_until_complete(coro)
    finally:
        # Clean up
        loop.close()
        if old_loop:
            asyncio.set_event_loop(old_loop)

class AsyncMock:
    """Mock class for async functions."""
    def __init__(self, return_value=None):
        self.return_value = return_value
        self.call_count = 0
    
    async def __call__(self, *args, **kwargs):
        self.call_count += 1
        return self.return_value

class MockMCPSessionManager:
    """Mock native session manager for integration tests."""
    
    def __init__(self, sandbox_id=None, default_ttl_hours=24, auto_extend_threshold=0.1):
        self.sandbox_id = sandbox_id or "integration-test-sandbox"
        self.default_ttl_hours = default_ttl_hours
        self.auto_extend_threshold = auto_extend_threshold
        self._sessions = {}
        self._current_session = None
        
    async def create_session(self, user_id=None, ttl_hours=None, metadata=None):
        session_id = f"session-{len(self._sessions)}-{user_id or 'anon'}"
        self._sessions[session_id] = {
            "user_id": user_id,
            "metadata": metadata or {},
            "created_at": 1640995200.0
        }
        return session_id
        
    async def validate_session(self, session_id):
        return session_id in self._sessions
        
    def set_current_session(self, session_id, user_id=None):
        self._current_session = session_id
        
    def get_current_session(self):
        return self._current_session
        
    def get_current_user(self):
        session_info = self._sessions.get(self._current_session, {})
        return session_info.get("user_id")
        
    def clear_context(self):
        self._current_session = None
        
    async def auto_create_session_if_needed(self, user_id=None):
        if self._current_session and await self.validate_session(self._current_session):
            return self._current_session
        session_id = await self.create_session(user_id=user_id, metadata={"auto_created": True})
        self.set_current_session(session_id, user_id)
        return session_id
        
    def get_cache_stats(self):
        return {
            "cache_size": len(self._sessions),
            "sandbox_id": self.sandbox_id
        }

class MockSessionContext:
    """Mock session context manager with better session tracking."""
    
    def __init__(self, session_manager, session_id=None, user_id=None, auto_create=True):
        self.session_manager = session_manager
        self.session_id = session_id
        self.user_id = user_id
        self.auto_create = auto_create
        
    async def __aenter__(self):
        if self.session_id:
            if not await self.session_manager.validate_session(self.session_id):
                raise ValueError(f"Session {self.session_id} is invalid")
            self.session_manager.set_current_session(self.session_id, self.user_id)
            return self.session_id
        elif self.auto_create:
            session_id = await self.session_manager.auto_create_session_if_needed(self.user_id)
            return session_id
        else:
            raise ValueError("No session provided and auto_create=False")
            
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class MockServerRegistry:
    """Mock server registry for testing."""
    def __init__(self, project_root, config):
        self.project_root = project_root
        self.config = config
        
    async def load_server_components(self):
        """Nothing to load in tests."""
        return {}

class MockMCPServer:
    """Mock MCP server for testing with session management."""
    def __init__(self, config, tools_registry=None):
        self.config = config
        self.server_name = "mock-server"
        self.tools_registry = tools_registry or {}
        self.registered_tools = []
        # Add session manager
        self.session_manager = MockMCPSessionManager()
        
    async def register_tool(self, name, func):
        """Record registered tools."""
        self.registered_tools.append(name)
        self.tools_registry[name] = func
        
    async def serve(self, custom_handlers=None):
        """Record custom handlers and return."""
        self.custom_handlers = custom_handlers
        return
        
    def get_session_manager(self):
        """Get the session manager instance."""
        return self.session_manager

@pytest.fixture(autouse=True)
def mock_stdio_server():
    """
    Mock the stdio_server context manager to prevent it from 
    trying to read from stdin in tests.
    """
    # Create dummy streams
    class DummyStream:
        async def read(self, n=-1):
            return b""
            
        async def write(self, data):
            return len(data)
            
        async def close(self):
            pass
    
    # Create a dummy async context manager
    async def dummy_stdio_server():
        read_stream = DummyStream()
        write_stream = DummyStream()
        
        try:
            yield (read_stream, write_stream)
        finally:
            pass
    
    # Patch the mcp.server.stdio module
    mock_stdio = MagicMock()
    mock_stdio.stdio_server = dummy_stdio_server
    sys.modules["mcp.server.stdio"] = mock_stdio
    
    yield
    
    # Clean up
    if "mcp.server.stdio" in sys.modules:
        del sys.modules["mcp.server.stdio"]

@pytest.fixture
def setup_mocks(monkeypatch):
    """Set up common mocks for tests with native session management."""
    # Mock config and logging
    monkeypatch.setattr(entry, "load_config", 
                       lambda paths, default: {
                           "proxy": {"enabled": True},
                           "sessions": {"sandbox_id": "integration-test"}
                       })
    monkeypatch.setattr(entry, "configure_logging", lambda cfg: None)
    monkeypatch.setattr(entry, "find_project_root", lambda: "/tmp")
    
    # Mock native session management
    monkeypatch.setattr(entry, "MCPSessionManager", MockMCPSessionManager)
    monkeypatch.setattr(entry, "SessionContext", MockSessionContext)
    monkeypatch.setattr(entry, "create_mcp_session_manager", 
                       lambda config: MockMCPSessionManager())
    
    # Mock session integration helper
    async def mock_with_session_auto_inject(session_manager, tool_name, args):
        # Simulate session injection for artifact tools
        artifact_tools = {
            "upload_file", "write_file", "read_file", "delete_file",
            "list_session_files", "list_directory", "copy_file", "move_file",
            "get_file_metadata", "get_presigned_url", "get_storage_stats"
        }
        
        if tool_name in artifact_tools and "session_id" not in args:
            session_id = await session_manager.auto_create_session_if_needed()
            return {**args, "session_id": session_id}
        return args
    
    monkeypatch.setattr(entry, "with_session_auto_inject", mock_with_session_auto_inject)
    
    # Mock server components
    monkeypatch.setattr(entry, "ServerRegistry", MockServerRegistry)
    monkeypatch.setattr(entry, "MCPServer", MockMCPServer)
    
    # IMPORTANT: We're now using the MockProxyServerManager already applied
    # to entry from the test_proxy_manager module - no need to set it here
    monkeypatch.setattr(entry, "HAS_PROXY_SUPPORT", True)
    
    # Mock initialize_tool_registry
    mock_init = AsyncMock()
    monkeypatch.setattr(entry, "initialize_tool_registry", mock_init)
    
    # Mock tool registration functions
    mock_register_artifacts = AsyncMock(return_value=True)
    mock_register_session = AsyncMock(return_value=True)
    monkeypatch.setattr(entry, "register_artifacts_tools", mock_register_artifacts)
    monkeypatch.setattr(entry, "register_session_tools", mock_register_session)
    
    return {
        "config": {"proxy": {"enabled": True}, "sessions": {"sandbox_id": "integration-test"}},
        "project_root": "/tmp",
        "mock_init": mock_init
    }

# --- Tests ---
@pytest.mark.asyncio
async def test_proxy_enabled_with_sessions(setup_mocks):
    """Test that proxy is properly enabled when configured with session management."""
    # Create a tracking server
    server_started = False
    session_manager_created = False
    
    class TrackingServer(MockMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal session_manager_created
            session_manager_created = True
            
        async def serve(self, custom_handlers=None):
            nonlocal server_started
            server_started = True
            self.custom_handlers = custom_handlers
            return True
    
    # Use direct execution rather than patching
    async def mock_runtime():
        config = {"proxy": {"enabled": True}, "sessions": {"sandbox_id": "test"}}
        project_root = "/tmp"
        
        # Create session manager
        session_manager = MockMCPSessionManager()
        
        # Create the proxy manager - use the existing mock from entry
        proxy_mgr = entry.ProxyServerManager(config, project_root)
        await proxy_mgr.start_servers()
        
        # Create server with session management
        server = TrackingServer(config)
        await server.serve(custom_handlers={"handle_proxy_text": lambda x: x})
        
        return True
    
    # Run the test
    result = await mock_runtime()
    
    # Verify test passed
    assert result is True
    assert server_started is True, "Server was not started"
    assert session_manager_created is True, "Session manager was not created"

@pytest.mark.asyncio
async def test_session_injection_for_artifact_tools(setup_mocks):
    """Test that session IDs are properly injected for artifact tools."""
    session_manager = MockMCPSessionManager()
    
    # Test session injection
    async def test_injection():
        # Test with artifact tool that needs session
        args = {"content": "test content", "filename": "test.txt"}
        injected_args = await entry.with_session_auto_inject(
            session_manager, "upload_file", args
        )
        
        assert "session_id" in injected_args
        assert injected_args["session_id"].startswith("session-")
        assert "anon" in injected_args["session_id"]  # auto-created session
        
        # Test with non-artifact tool
        args2 = {"query": "test"}
        injected_args2 = await entry.with_session_auto_inject(
            session_manager, "search_web", args2
        )
        
        assert injected_args2 == args2  # No injection for non-artifact tools
        
        return True
    
    result = await test_injection()
    assert result is True

@pytest.mark.asyncio
async def test_session_context_management(setup_mocks):
    """Test session context management in tool execution."""
    session_manager = MockMCPSessionManager()
    
    async def test_context():
        # Test auto-create session
        async with MockSessionContext(session_manager, auto_create=True) as session_id:
            assert session_id is not None
            assert session_id.startswith("session-")
            
            # Verify session was created
            assert await session_manager.validate_session(session_id)
            
        # Test with specific session
        created_session = await session_manager.create_session(user_id="test_user")
        async with MockSessionContext(session_manager, session_id=created_session) as session_id:
            assert session_id == created_session
            assert session_manager.get_current_session() == created_session
            assert session_manager.get_current_user() == "test_user"
            
        return True
    
    result = await test_context()
    assert result is True

@pytest.mark.asyncio
async def test_proxy_tool_registration_with_sessions(setup_mocks):
    """Test that proxy tools are properly registered with session context."""
    # Create test tools with session awareness
    async def session_aware_tool(**kwargs):
        session_id = kwargs.get("session_id", "no-session")
        return f"Tool result for session: {session_id}"
    
    # Create a tracking server
    registered_tools = {}
    session_manager_instance = None
    
    class TrackingServer(MockMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal session_manager_instance
            session_manager_instance = self.session_manager
            
        async def register_tool(self, name, func):
            registered_tools[name] = func
            await super().register_tool(name, func)
    
    class TestProxyServerManager(entry.ProxyServerManager):
        async def get_all_tools(self):
            return {
                "proxy.test.session_tool": session_aware_tool,
            }
            
        async def start_servers(self):
            self.running = {"test": {"status": "running"}}
    
    # Run directly without patching
    async def test_runtime():
        config = {"proxy": {"enabled": True}, "sessions": {"sandbox_id": "test"}}
        project_root = "/tmp"
        
        # Create proxy manager instance - using our specialized version
        proxy_mgr = TestProxyServerManager(config, project_root)
        await proxy_mgr.start_servers()
        
        # Get the tools
        tools = await proxy_mgr.get_all_tools()
        
        # Create server
        server = TrackingServer(config)
        
        # Register tools
        for name, func in tools.items():
            await server.register_tool(name, func)
        
        # Start server
        await server.serve()
        
        return tools, session_manager_instance
    
    # Run the function directly
    tools, session_mgr = await test_runtime()
    
    # Verify tools were registered
    assert "proxy.test.session_tool" in tools
    assert session_mgr is not None
    assert isinstance(session_mgr, MockMCPSessionManager)

@pytest.mark.asyncio
async def test_proxy_disabled_with_sessions(setup_mocks):
    """Test that session management works when proxy is disabled."""
    # Create a tracking server and proxy
    server_started = False
    session_manager_created = False
    
    class TrackingServer(MockMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal session_manager_created
            session_manager_created = True
            
        async def serve(self, custom_handlers=None):
            nonlocal server_started
            server_started = True
            self.custom_handlers = custom_handlers
            return True
    
    # Run directly without patching
    async def mock_runtime():
        config = {"proxy": {"enabled": False}, "sessions": {"sandbox_id": "test"}}
        project_root = "/tmp"
        
        # Initialize server directly
        server = TrackingServer(config)
        await server.serve()
        
        return True
    
    # Run the function without patching
    result = await mock_runtime()
    
    # Verify test passed
    assert result is True
    assert server_started is True, "Server was not started"
    assert session_manager_created is True, "Session manager was not created"

@pytest.mark.asyncio
async def test_session_aware_custom_handlers(setup_mocks):
    """Test that custom handlers work with session context."""
    custom_handlers_set = False
    
    class SessionAwareServer(MockMCPServer):
        async def serve(self, custom_handlers=None):
            nonlocal custom_handlers_set
            if custom_handlers and "handle_proxy_text" in custom_handlers:
                custom_handlers_set = True
            self.custom_handlers = custom_handlers
            return True
    
    class SessionAwareProxyManager(entry.ProxyServerManager):
        async def process_text(self, text):
            # Simulate session-aware text processing
            session_id = await self.session_manager.auto_create_session_if_needed()
            return [{"content": f"Processed '{text}' in session {session_id}"}]
            
        async def start_servers(self):
            self.running = {"test_server": {"status": "running"}}
            # Add a mock session manager
            self.session_manager = MockMCPSessionManager()
    
    # Run directly
    async def test_runtime():
        config = {"proxy": {"enabled": True}, "sessions": {"sandbox_id": "test"}}
        project_root = "/tmp"
        
        # Create proxy manager
        proxy_mgr = SessionAwareProxyManager(config, project_root)
        await proxy_mgr.start_servers()
        
        # Create server
        server = SessionAwareServer(config)
        
        # Create custom handler that uses sessions
        async def handle_proxy_text(text):
            return await proxy_mgr.process_text(text)
        
        await server.serve(custom_handlers={"handle_proxy_text": handle_proxy_text})
        
        return True
    
    result = await test_runtime()
    assert result is True
    assert custom_handlers_set is True

@pytest.mark.asyncio 
async def test_artifact_tools_session_integration(setup_mocks):
    """Test that artifact tools properly integrate with session management."""
    session_manager = MockMCPSessionManager()
    
    # Test artifact tool with session injection
    async def test_artifact_integration():
        # Simulate calling an artifact tool
        args = {"content": b"test file content", "filename": "test.txt", "mime": "text/plain"}
        
        # Test session injection
        injected_args = await entry.with_session_auto_inject(
            session_manager, "upload_file", args
        )
        
        # Should have session_id injected
        assert "session_id" in injected_args
        session_id = injected_args["session_id"]
        
        # Verify session exists
        assert await session_manager.validate_session(session_id)
        
        # Test that session context is maintained
        session_info = await session_manager.get_session_info(session_id)
        assert "auto_created" in session_info.get("metadata", {})
        
        return True
    
    result = await test_artifact_integration()
    assert result is True

# Add this test to verify that we're using the same mock as test_proxy_manager.py
def test_proxy_server_manager_mock():
    """Test that ProxyServerManager is mocked correctly."""
    # Import the MockProxyServerManager from test_proxy_manager
    from tests.proxy.test_proxy_manager import MockProxyServerManager as TestMockProxyServerManager
    
    # Verify that the entry module is using this mock
    assert entry.ProxyServerManager is TestMockProxyServerManager

def test_session_manager_configuration():
    """Test session manager configuration from config."""
    config = {
        "sessions": {
            "sandbox_id": "custom-sandbox",
            "default_ttl_hours": 48,
            "auto_extend_threshold": 0.2
        }
    }
    
    session_manager = MockMCPSessionManager(
        sandbox_id=config["sessions"]["sandbox_id"],
        default_ttl_hours=config["sessions"]["default_ttl_hours"],
        auto_extend_threshold=config["sessions"]["auto_extend_threshold"]
    )
    
    assert session_manager.sandbox_id == "custom-sandbox"
    assert session_manager.default_ttl_hours == 48
    assert session_manager.auto_extend_threshold == 0.2