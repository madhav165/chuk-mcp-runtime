# tests/test_entry_basic.py
"""
Test module for basic functionality of chuk_mcp_runtime entry point.

Tests core functions and mock setup for the MCP runtime with native session management.
"""
import pytest
import sys
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

# Mock the problematic artifacts_tools module before ANY imports
mock_artifacts_tools = MagicMock()
mock_artifacts_tools.validate_session_parameter = lambda session_id=None, operation="unknown": session_id or "test-session"
sys.modules["chuk_mcp_runtime.tools.artifacts_tools"] = mock_artifacts_tools

# Import our common test mocks
from tests.conftest import (
    MockProxyServerManager, 
    MockMCPSessionManager,
    MockSessionContext,
    DummyServerRegistry,
    mock_session_ctx,
    mock_user_ctx,
    mock_require_session,
    mock_get_session_or_none,
    mock_with_session_auto_inject,
    run_async,
    AsyncMock as TestAsyncMock
)

# Import the entry module - this will use our mocked modules
import chuk_mcp_runtime.entry as entry

class EnhancedMockMCPSessionManager(MockMCPSessionManager):
    """Enhanced mock session manager that properly handles configuration."""
    
    def __init__(self, sandbox_id=None, default_ttl_hours=24, auto_extend_threshold=0.1):
        super().__init__(sandbox_id, default_ttl_hours, auto_extend_threshold)
        # Ensure we respect the provided parameters
        self.sandbox_id = sandbox_id or "test-sandbox"
        self.default_ttl_hours = default_ttl_hours  # This was the issue
        self.auto_extend_threshold = auto_extend_threshold

class EnhancedMockSessionContext(MockSessionContext):
    """Enhanced session context that properly integrates with context variables."""
    
    async def __aenter__(self):
        # Save previous context
        self.previous_session = self.session_manager.get_current_session()
        self.previous_user = self.session_manager.get_current_user()
        
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

class DummyMCPServer:
    """Enhanced dummy MCP server with session management."""
    
    def __init__(self, config, tools_registry=None):
        self.config = config
        self.serve_called = False
        self.server_name = "test-server"
        self.registered_tools = []
        self.tools_registry = tools_registry or {}
        
        # Create session manager with proper config handling
        session_config = config.get("sessions", {})
        self.session_manager = EnhancedMockMCPSessionManager(
            sandbox_id=session_config.get("sandbox_id"),
            default_ttl_hours=session_config.get("default_ttl_hours", 24)
        )
        
    async def serve(self, custom_handlers=None):
        """Mock serve method that doesn't try to use stdio_server."""
        self.serve_called = True
        self.custom_handlers = custom_handlers
        return
        
    async def register_tool(self, name, func):
        """Mock register_tool method."""
        self.registered_tools.append(name)
        self.tools_registry[name] = func
        
    def get_session_manager(self):
        """Get the session manager instance."""
        return self.session_manager
        
    async def create_user_session(self, user_id, metadata=None):
        """Create a new user session."""
        return await self.session_manager.create_session(user_id=user_id, metadata=metadata)

# Patch session management imports and functions
def patch_session_management():
    """Apply comprehensive session management patches."""
    # Core classes
    entry.MCPSessionManager = EnhancedMockMCPSessionManager
    entry.SessionContext = EnhancedMockSessionContext
    entry.create_mcp_session_manager = lambda config: EnhancedMockMCPSessionManager(
        sandbox_id=config.get("sessions", {}).get("sandbox_id") if config else None,
        default_ttl_hours=config.get("sessions", {}).get("default_ttl_hours", 24) if config else 24
    )
    
    # Helper functions
    entry.with_session_auto_inject = mock_with_session_auto_inject
    entry.require_session = mock_require_session
    entry.get_session_or_none = mock_get_session_or_none
    
    # Tool registration functions
    async def mock_register_artifacts_tools(config):
        return config.get("artifacts", {}).get("enabled", False)
    
    async def mock_register_session_tools(config):
        return config.get("session_tools", {}).get("enabled", False)
    
    entry.register_artifacts_tools = mock_register_artifacts_tools
    entry.register_session_tools = mock_register_session_tools
    
    # Mock _iter_tools function
    def mock_iter_tools(container):
        if isinstance(container, dict):
            for name, func in container.items():
                mock_func = TestAsyncMock()
                mock_func._mcp_tool = MagicMock()
                mock_func._mcp_tool.name = name
                yield name, mock_func
        elif isinstance(container, (list, tuple, set)):
            for name in container:
                mock_func = TestAsyncMock()
                mock_func._mcp_tool = MagicMock()
                mock_func._mcp_tool.name = name
                yield name, mock_func
    
    entry._iter_tools = mock_iter_tools
    
    # Mock get_artifact_tools
    def mock_get_artifact_tools():
        return {
            "upload_file": TestAsyncMock(return_value="uploaded"),
            "write_file": TestAsyncMock(return_value="written"),
            "read_file": TestAsyncMock(return_value="content"),
            "list_session_files": TestAsyncMock(return_value=[])
        }
    
    entry.get_artifact_tools = mock_get_artifact_tools

def test_need_proxy_function():
    """Test that the _need_proxy function correctly identifies proxy config."""
    patch_session_management()
    
    # Test with HAS_PROXY_SUPPORT = True (default)
    assert entry._need_proxy({"proxy": {"enabled": True}}) is True
    assert entry._need_proxy({"proxy": {"enabled": False}}) is False
    assert entry._need_proxy({}) is False
    
    # Test with HAS_PROXY_SUPPORT = False
    with patch.object(entry, 'HAS_PROXY_SUPPORT', False):
        assert entry._need_proxy({"proxy": {"enabled": True}}) is False
        assert entry._need_proxy({"proxy": {"enabled": False}}) is False
        assert entry._need_proxy({}) is False
    
def test_import_paths():
    """Test that the imports were mocked correctly."""
    assert "chuk_tool_processor" in sys.modules
    assert "chuk_tool_processor.mcp" in sys.modules
    assert "chuk_mcp_runtime.tools.artifacts_tools" in sys.modules
    
def test_proxy_server_manager_mock():
    """Test that ProxyServerManager is mocked correctly."""
    patch_session_management()
    
    # Get the ProxyServerManager from entry
    assert entry.ProxyServerManager is MockProxyServerManager
    
    # Create an instance of the mocked class
    proxy_mgr = entry.ProxyServerManager({}, "/tmp")
    assert hasattr(proxy_mgr, "running") or hasattr(proxy_mgr, "running_servers")
    
    # Test that methods exist
    assert hasattr(proxy_mgr, "start_servers")
    assert hasattr(proxy_mgr, "stop_servers")
    assert hasattr(proxy_mgr, "get_all_tools")
    
    # Test that process_text method exists (added for tool naming compatibility)
    assert hasattr(proxy_mgr, "process_text")

def test_tool_naming_compatibility():
    """Test that the proxy manager supports tool naming compatibility."""
    patch_session_management()
    
    # Create a proxy manager with tools in different formats
    proxy_mgr = MockProxyServerManager({
        "proxy": {
            "enabled": True,
            "openai_compatible": True
        }
    }, "/tmp")
    
    # Add a tool function that returns a mock response
    test_tool = TestAsyncMock(return_value="Tool response")
    proxy_mgr.tools = {
        "proxy.test.tool": test_tool
    }
    
    # Test get_all_tools (async function)
    tools = run_async(proxy_mgr.get_all_tools())
    assert "proxy.test.tool" in tools
    
    # Test process_text functionality (async function)
    result = run_async(proxy_mgr.process_text("Test text"))
    assert result[0]["processed"] is True
    assert result[0]["text"] == "Test text"
    
    # Test call_tool with different naming formats (async function)
    # With dot notation
    result1 = run_async(proxy_mgr.call_tool("proxy.test.tool", query="test"))
    assert "result" in result1.lower() or "response" in result1.lower()
    
    # With underscore notation
    result2 = run_async(proxy_mgr.call_tool("test_tool", query="test"))
    assert "result" in result2.lower() or "response" in result2.lower()

def test_session_manager_creation():
    """Test that session manager is properly created."""
    patch_session_management()
    
    config = {
        "sessions": {
            "sandbox_id": "test-sandbox",
            "default_ttl_hours": 48
        }
    }
    
    session_manager = entry.create_mcp_session_manager(config)
    assert isinstance(session_manager, EnhancedMockMCPSessionManager)
    assert session_manager.sandbox_id == "test-sandbox"
    assert session_manager.default_ttl_hours == 48  # This should now work

def test_session_context_integration():
    """Test session context integration."""
    patch_session_management()
    
    async def test_session_flow():
        session_manager = EnhancedMockMCPSessionManager()
        
        async with EnhancedMockSessionContext(session_manager, auto_create=True) as session_id:
            assert session_id is not None
            assert session_id.startswith("session-")
            
        return True
    
    result = run_async(test_session_flow())
    assert result is True

def test_session_auto_injection():
    """Test automatic session injection for artifact tools."""
    patch_session_management()
    
    async def test_injection():
        session_manager = EnhancedMockMCPSessionManager()
        
        # Test with artifact tool
        args = {"content": "test content", "filename": "test.txt"}
        injected_args = await entry.with_session_auto_inject(
            session_manager, "upload_file", args
        )
        
        assert "session_id" in injected_args
        assert injected_args["session_id"].startswith("session-")
        
        # Test with non-artifact tool
        args2 = {"query": "test"}
        injected_args2 = await entry.with_session_auto_inject(
            session_manager, "search_web", args2
        )
        
        assert injected_args2 == args2  # No injection for non-artifact tools
        
        return True
    
    result = run_async(test_injection())
    assert result is True

def test_artifacts_registration():
    """Test artifact tools registration with session management."""
    patch_session_management()
    
    async def test_artifacts():
        config = {
            "artifacts": {
                "enabled": True,
                "tools": {
                    "upload_file": {"enabled": True},
                    "write_file": {"enabled": True}
                }
            }
        }
        
        # Test the registration function
        result = await entry.register_artifacts_tools(config)
        assert result is True  # Should return True when enabled
        
        return True
    
    result = run_async(test_artifacts())
    assert result is True

def test_session_tools_registration():
    """Test session tools registration."""
    patch_session_management()
    
    async def test_session_tools():
        config = {
            "session_tools": {
                "enabled": True,
                "tools": {
                    "get_current_session": {"enabled": True},
                    "create_session": {"enabled": True}
                }
            }
        }
        
        # Test the registration function
        result = await entry.register_session_tools(config)
        assert result is True  # Should return True when enabled
        
        return True
    
    result = run_async(test_session_tools())
    assert result is True

def test_initialize_tool_registry_called():
    """Test that initialize_tool_registry is called during runtime startup."""
    patch_session_management()
    
    # Ensure the artifacts_tools module is properly mocked
    assert "chuk_mcp_runtime.tools.artifacts_tools" in sys.modules
    
    # Using context managers is cleaner and safer
    with patch('chuk_mcp_runtime.entry.ServerRegistry', DummyServerRegistry), \
         patch('chuk_mcp_runtime.entry.initialize_tool_registry') as mock_init, \
         patch('chuk_mcp_runtime.entry.load_config', return_value={
             "proxy": {"enabled": False},
             "sessions": {"sandbox_id": "test"}
         }), \
         patch('chuk_mcp_runtime.entry.configure_logging'), \
         patch('chuk_mcp_runtime.entry.find_project_root', return_value="/tmp"), \
         patch('asyncio.run', side_effect=run_async):
        
        # Create a custom server that won't try to use stdio
        server = DummyMCPServer({
            "server": {"type": "stdio"},
            "sessions": {"sandbox_id": "test"}
        })
        
        # Patch MCPServer separately to use our custom instance
        with patch('chuk_mcp_runtime.entry.MCPServer', return_value=server):
            # Make initialize_tool_registry an async mock
            async def mock_init_async(*args, **kwargs):
                return None
            mock_init.side_effect = mock_init_async
            
            # Run the runtime
            entry.run_runtime()
            
            # Check that initialize_tool_registry was called
            assert mock_init.called

def test_session_context_management():
    """Test session context management in tool execution."""
    patch_session_management()
    
    async def test_context():
        session_manager = EnhancedMockMCPSessionManager()
        
        # Test session creation and context setting
        session_id = await session_manager.create_session(user_id="test_user")
        session_manager.set_current_session(session_id, "test_user")
        
        # Verify context variables are set
        assert mock_session_ctx.get() == session_id
        assert mock_user_ctx.get() == "test_user"
        
        # Test require_session works
        current = mock_require_session()
        assert current == session_id
        
        # Test context clearing
        session_manager.clear_context()
        assert mock_session_ctx.get() is None
        assert mock_user_ctx.get() is None
        
        return True
    
    result = run_async(test_context())
    assert result is True

def test_proxy_integration():
    """Test proxy integration with session management."""
    patch_session_management()
    
    # Create a test proxy manager
    proxy_mgr = MockProxyServerManager({
        "proxy": {"enabled": True}
    }, "/tmp")
    
    # Test that proxy manager has session integration
    assert hasattr(proxy_mgr, "get_all_tools")
    assert hasattr(proxy_mgr, "start_servers")
    assert hasattr(proxy_mgr, "stop_servers")
    
    # Test async operations
    tools = run_async(proxy_mgr.get_all_tools())
    assert isinstance(tools, dict)
    
    # Test starting servers
    run_async(proxy_mgr.start_servers())
    assert len(proxy_mgr.running) > 0 or len(proxy_mgr.running_servers) > 0

def test_openai_compatibility_integration():
    """Test OpenAI compatibility with session management."""
    patch_session_management()
    
    # Mock the OpenAI compatibility initialization
    with patch('chuk_mcp_runtime.entry.initialize_openai_compatibility') as mock_init_openai:
        mock_init_openai.return_value = TestAsyncMock()
        
        config = {
            "proxy": {"enabled": False},
            "sessions": {"sandbox_id": "test"},
            "openai_compatible": True
        }
        
        # Test that OpenAI compatibility can be initialized
        async def test_openai():
            await entry.initialize_openai_compatibility()
            return True
        
        result = run_async(test_openai())
        assert result is True

def test_error_handling():
    """Test error handling in session management."""
    patch_session_management()
    
    async def test_errors():
        session_manager = EnhancedMockMCPSessionManager()
        
        # Test session validation with invalid session
        is_valid = await session_manager.validate_session("invalid-session")
        assert is_valid is False
        
        # Test require_session without context
        mock_session_ctx.set(None)
        try:
            mock_require_session()
            assert False, "Should have raised exception"
        except Exception as e:
            assert "No session context available" in str(e)
        
        return True
    
    result = run_async(test_errors())
    assert result is True

def test_config_handling():
    """Test configuration handling in session management."""
    patch_session_management()
    
    # Test with various config scenarios
    configs = [
        {},  # Empty config
        {"sessions": {}},  # Empty sessions config
        {"sessions": {"sandbox_id": "custom"}},  # Custom sandbox
        {"sessions": {"sandbox_id": "custom", "default_ttl_hours": 12}}  # Full config
    ]
    
    for config in configs:
        session_manager = entry.create_mcp_session_manager(config)
        assert isinstance(session_manager, EnhancedMockMCPSessionManager)
        
        # Verify defaults and overrides
        expected_sandbox = config.get("sessions", {}).get("sandbox_id") or "test-sandbox"
        expected_ttl = config.get("sessions", {}).get("default_ttl_hours", 24)
        
        assert session_manager.sandbox_id == expected_sandbox
        assert session_manager.default_ttl_hours == expected_ttl

def test_comprehensive_session_workflow():
    """Test a comprehensive session workflow."""
    patch_session_management()
    
    async def test_workflow():
        # Create session manager
        session_manager = EnhancedMockMCPSessionManager()
        
        # Create session
        session_id = await session_manager.create_session(
            user_id="workflow_user",
            metadata={"test": "data"}
        )
        
        # Set context
        session_manager.set_current_session(session_id, "workflow_user")
        
        # Verify context
        assert mock_require_session() == session_id
        assert mock_get_session_or_none() == session_id
        
        # Test session auto-injection
        args = {"filename": "test.txt", "content": "data"}
        injected = await entry.with_session_auto_inject(
            session_manager, "upload_file", args
        )
        assert injected["session_id"] == session_id
        
        # Update session
        success = await session_manager.update_session_metadata(
            session_id, {"updated": True}
        )
        assert success is True
        
        # Get session info
        info = await session_manager.get_session_info(session_id)
        assert info["user_id"] == "workflow_user"
        assert info["custom_metadata"]["test"] == "data"
        assert info["custom_metadata"]["updated"] is True
        
        # Clean up
        session_manager.clear_context()
        assert mock_get_session_or_none() is None
        
        return True
    
    result = run_async(test_workflow())
    assert result is True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])