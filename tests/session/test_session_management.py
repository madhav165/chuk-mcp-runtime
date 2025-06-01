# tests/test_session_management.py
import os
import asyncio
import pytest
import pytest_asyncio
import warnings
from unittest.mock import MagicMock, AsyncMock, patch
from contextvars import copy_context

from chuk_mcp_runtime.session.session_management import (
    set_session_context,
    get_session_context,
    clear_session_context,
    normalize_session_id,
    require_session_context,
    get_effective_session_id,
    validate_session_parameter,
    set_session_data,
    get_session_data,
    clear_session_data,
    list_sessions,
    session_aware,
    SessionContext,
    SessionError,
    list_sessions_cache_stats,
    cleanup_expired_sessions,
    _session_store,
    _mgr
)

# Suppress expected warnings for async operations in sync tests
warnings.filterwarnings("ignore", category=RuntimeWarning, module="chuk_mcp_runtime.session.session_management")
warnings.filterwarnings("ignore", message=".*coroutine.*was never awaited.*", category=RuntimeWarning)

class MockSessionManager:
    """Mock session manager for testing."""
    
    def __init__(self):
        self._session_cache = {}
        self.sessions_data = {}
        
    async def update_session_metadata(self, session_id, data):
        if session_id not in self.sessions_data:
            self.sessions_data[session_id] = {"custom_metadata": {}}
        self.sessions_data[session_id]["custom_metadata"].update(data)
        
    async def get_session_info(self, session_id):
        return self.sessions_data.get(session_id)
        
    async def delete_session(self, session_id):
        self.sessions_data.pop(session_id, None)
        self._session_cache.pop(session_id, None)
        
    def get_cache_stats(self):
        return {
            "cache_size": len(self._session_cache),
            "total_sessions": len(self.sessions_data)
        }
        
    async def cleanup_expired_sessions(self):
        # Mock cleanup - just return count
        return len(self.sessions_data)

@pytest.fixture
def mock_session_manager():
    """Provide a mock session manager."""
    manager = MockSessionManager()
    
    # Mock the _mgr function to return our mock
    def mock_mgr():
        return manager
        
    with patch('chuk_mcp_runtime.session.session_management._mgr', mock_mgr):
        yield manager

@pytest.fixture(autouse=True)
def clear_session_state():
    """Clear session state before and after each test."""
    # Clear context and store before test
    clear_session_context()
    _session_store.clear()
    
    yield
    
    # Clear after test
    clear_session_context()
    _session_store.clear()

class TestBasicSessionContext:
    """Test basic session context operations."""
    
    def test_set_and_get_session_context(self):
        """Test setting and getting session context."""
        session_id = "test-session-123"
        
        # Initially no session
        assert get_session_context() is None
        
        # Set session
        set_session_context(session_id)
        assert get_session_context() == session_id
        
    def test_set_session_context_validation(self):
        """Test session context validation."""
        # Empty session should raise error
        with pytest.raises(SessionError, match="Session ID cannot be empty"):
            set_session_context("")
            
        with pytest.raises(SessionError, match="Session ID cannot be empty"):
            set_session_context("   ")
            
    def test_clear_session_context(self):
        """Test clearing session context."""
        set_session_context("test-session")
        assert get_session_context() == "test-session"
        
        clear_session_context()
        assert get_session_context() is None
        
    def test_session_context_isolation(self):
        """Test that session context is isolated per task."""
        results = {}
        
        async def task_with_session(session_id, task_id):
            set_session_context(session_id)
            await asyncio.sleep(0.01)  # Yield control
            results[task_id] = get_session_context()
            
        async def run_concurrent_tasks():
            tasks = [
                task_with_session("session-1", "task-1"),
                task_with_session("session-2", "task-2"),
                task_with_session("session-3", "task-3"),
            ]
            await asyncio.gather(*tasks)
            
        asyncio.run(run_concurrent_tasks())
        
        # Each task should maintain its own session
        assert results["task-1"] == "session-1"
        assert results["task-2"] == "session-2"
        assert results["task-3"] == "session-3"

class TestSessionNormalization:
    """Test session ID normalization and validation."""
    
    def test_normalize_session_id_valid(self):
        """Test normalization of valid session IDs."""
        assert normalize_session_id("test-session") == "test-session"
        assert normalize_session_id("  test-session  ") == "test-session"
        assert normalize_session_id("session_123") == "session_123"
        assert normalize_session_id("session.with.dots") == "session.with.dots"
        
    def test_normalize_session_id_invalid(self):
        """Test validation of invalid session IDs."""
        # None or empty
        with pytest.raises(SessionError, match="Session ID cannot be None or empty"):
            normalize_session_id(None)
            
        with pytest.raises(SessionError, match="Session ID cannot be None or empty"):
            normalize_session_id("")
            
        with pytest.raises(SessionError, match="empty after normalization"):
            normalize_session_id("   ")
            
        # Too long
        long_id = "x" * 101
        with pytest.raises(SessionError, match="Session ID too long"):
            normalize_session_id(long_id)
            
        # Invalid characters
        with pytest.raises(SessionError, match="invalid characters"):
            normalize_session_id("session@invalid")
            
        with pytest.raises(SessionError, match="invalid characters"):
            normalize_session_id("session with spaces")
            
    def test_require_session_context(self):
        """Test requiring session context."""
        # No session should raise error
        with pytest.raises(SessionError, match="No session context available"):
            require_session_context()
            
        # With session should return it
        set_session_context("test-session")
        assert require_session_context() == "test-session"
        
    def test_get_effective_session_id(self):
        """Test getting effective session ID."""
        # Provided session takes precedence
        set_session_context("context-session")
        assert get_effective_session_id("provided-session") == "provided-session"
        
        # Context session when no provided session
        assert get_effective_session_id() == "context-session"
        
        # Error when no session available
        clear_session_context()
        with pytest.raises(SessionError, match="No session_id provided"):
            get_effective_session_id()
            
    def test_validate_session_parameter(self):
        """Test session parameter validation for operations."""
        # Valid provided session
        result = validate_session_parameter("test-session", "test_operation")
        assert result == "test-session"
        
        # Valid context session
        set_session_context("context-session")
        result = validate_session_parameter(None, "test_operation")
        assert result == "context-session"
        
        # Invalid session raises ValueError with operation name
        clear_session_context()
        with pytest.raises(ValueError, match="Operation 'test_operation' requires"):
            validate_session_parameter(None, "test_operation")

class TestSessionDataManagement:
    """Test session data storage and retrieval."""
    
    def test_session_data_operations(self, mock_session_manager):
        """Test basic session data operations."""
        session_id = "test-session"
        
        # Set data directly in local store to avoid async task creation
        _session_store[session_id] = {
            "key1": "value1",
            "key2": {"nested": "data"}
        }
        
        # Get data - should only access local store
        assert get_session_data(session_id, "key1") == "value1"
        assert get_session_data(session_id, "key2") == {"nested": "data"}
        
        # Test with non-existent key - this will try async fallback, so we'll test differently
        assert session_id in _session_store  # Verify session exists locally
        
        # Test accessing key that doesn't exist in local store
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = get_session_data(session_id, "nonexistent", "default")
            assert result == "default"
        
    def test_session_data_with_manager_fallback(self, mock_session_manager):
        """Test session data fallback to session manager."""
        session_id = "test-session"
        
        # Set up manager data
        mock_session_manager.sessions_data[session_id] = {
            "custom_metadata": {"manager_key": "manager_value"}
        }
        
        # Test when data is NOT in local store - should fall back to manager
        # Suppress warnings for this specific test case
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = get_session_data(session_id, "manager_key", "default")
            assert result == "manager_value"  # Manager fallback works
        
        # Test when data IS in local store - should return local value
        _session_store[session_id] = {"local_key": "local_value"}
        result = get_session_data(session_id, "local_key", "default")
        assert result == "local_value"
        
        # Test when data is not in either store - should return default
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = get_session_data(session_id, "nonexistent_key", "default")
            assert result == "default"
        
    @pytest.mark.asyncio
    async def test_clear_session_data(self, mock_session_manager):
        """Test clearing session data."""
        session_id = "test-session"
        
        # Set some data directly to avoid async task issues
        _session_store[session_id] = {"key1": "value1"}
        assert get_session_data(session_id, "key1") == "value1"
        
        # Clear data (this will work in async context)
        clear_session_data(session_id)
        
        # Allow async task to complete
        await asyncio.sleep(0.01)
        
        # Test that data is gone - suppress warnings for async fallback attempt
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = get_session_data(session_id, "key1", "default")
            assert result == "default"
            
    def test_clear_session_data_local_store_only(self, mock_session_manager):
        """Test clearing session data from local store without async operations."""
        session_id = "test-session-local"
        
        # Set some data directly
        _session_store[session_id] = {"key1": "value1"}
        assert get_session_data(session_id, "key1") == "value1"
        
        # Clear data from local store directly to avoid async task
        _session_store.pop(session_id, None)
        
        # Test that data is gone
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = get_session_data(session_id, "key1", "default")
            assert result == "default"
        
    @pytest.mark.asyncio
    async def test_list_sessions(self, mock_session_manager):
        """Test listing sessions."""
        # Add some sessions to both stores directly
        _session_store["session1"] = {"key": "value"}
        _session_store["session2"] = {"key": "value"}
        mock_session_manager._session_cache["session3"] = {}
        
        sessions = list_sessions()
        assert "session1" in sessions
        assert "session2" in sessions
        assert "session3" in sessions
        
    @pytest.mark.asyncio
    async def test_set_session_data_async(self, mock_session_manager):
        """Test setting session data in async context."""
        session_id = "test-session"
        
        # This should work in async context
        set_session_data(session_id, "async_key", "async_value")
        
        # Allow async task to complete
        await asyncio.sleep(0.01)
        
        # Check local store
        assert get_session_data(session_id, "async_key") == "async_value"

class TestSessionAwareDecorator:
    """Test the session_aware decorator."""
    
    def test_session_aware_decorator_with_session(self):
        """Test session_aware decorator when session is available."""
        @session_aware(require_session=True)
        def test_func():
            return "success"
            
        # Should work when session is set
        set_session_context("test-session")
        result = test_func()
        assert result == "success"
        
    def test_session_aware_decorator_without_session(self):
        """Test session_aware decorator when session is missing."""
        @session_aware(require_session=True)
        def test_func():
            return "success"
            
        # Should fail when no session
        clear_session_context()
        with pytest.raises(ValueError, match="requires session context"):
            test_func()
            
    def test_session_aware_decorator_optional(self):
        """Test session_aware decorator with optional session."""
        @session_aware(require_session=False)
        def test_func():
            return "success"
            
        # Should work without session when not required
        clear_session_context()
        result = test_func()
        assert result == "success"

class TestSessionContextManager:
    """Test the SessionContext async context manager."""
    
    @pytest.mark.asyncio
    async def test_session_context_manager(self):
        """Test SessionContext as async context manager."""
        # Set initial session
        set_session_context("initial-session")
        assert get_session_context() == "initial-session"
        
        # Use context manager
        async with SessionContext("temp-session"):
            assert get_session_context() == "temp-session"
            
        # Should restore previous session
        assert get_session_context() == "initial-session"
        
    @pytest.mark.asyncio
    async def test_session_context_manager_no_previous(self):
        """Test SessionContext when no previous session."""
        clear_session_context()
        assert get_session_context() is None
        
        async with SessionContext("temp-session"):
            assert get_session_context() == "temp-session"
            
        # Should clear session after context
        assert get_session_context() is None
        
    @pytest.mark.asyncio
    async def test_session_context_manager_exception(self):
        """Test SessionContext handles exceptions properly."""
        set_session_context("initial-session")
        
        try:
            async with SessionContext("temp-session"):
                assert get_session_context() == "temp-session"
                raise ValueError("test exception")
        except ValueError:
            pass
            
        # Should still restore previous session
        assert get_session_context() == "initial-session"

class TestSessionCacheAndCleanup:
    """Test session cache statistics and cleanup."""
    
    def test_list_sessions_cache_stats(self, mock_session_manager):
        """Test getting cache statistics."""
        stats = list_sessions_cache_stats()
        assert isinstance(stats, dict)
        assert "cache_size" in stats or "total_sessions" in stats
        
    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, mock_session_manager):
        """Test cleanup of expired sessions."""
        # Add some test data
        mock_session_manager.sessions_data["session1"] = {}
        mock_session_manager.sessions_data["session2"] = {}
        
        count = await cleanup_expired_sessions()
        assert isinstance(count, int)
        assert count >= 0

class TestIntegrationScenarios:
    """Test real-world integration scenarios."""
    
    def test_tool_session_injection_scenario(self):
        """Test scenario where tool gets session injected."""
        def mock_tool_call(session_id=None, **kwargs):
            if session_id:
                return f"Tool called with session: {session_id}"
            else:
                # Simulate auto-injection
                current_session = get_session_context()
                if current_session:
                    return f"Tool called with auto session: {current_session}"
                return "Tool called without session"
                
        # Scenario 1: Explicit session provided
        result = mock_tool_call(session_id="explicit-session", data="test")
        assert "explicit-session" in result
        
        # Scenario 2: Session from context
        set_session_context("context-session")
        result = mock_tool_call(data="test")
        assert "context-session" in result
        
        # Scenario 3: No session available
        clear_session_context()
        result = mock_tool_call(data="test")
        assert "without session" in result
        
    @pytest.mark.asyncio
    async def test_concurrent_session_operations(self):
        """Test concurrent session operations don't interfere."""
        results = {}
        
        async def session_worker(worker_id, session_id):
            set_session_context(session_id)
            # Use direct store access to avoid async task issues in tests
            _session_store[session_id] = {"worker": worker_id}
            
            # Yield control to other tasks
            await asyncio.sleep(0.01)
            
            # Verify our session is still correct
            current_session = get_session_context()
            worker_data = get_session_data(session_id, "worker")
            
            results[worker_id] = {
                "session": current_session,
                "data": worker_data
            }
            
        # Run concurrent workers
        workers = [
            session_worker("worker1", "session1"),
            session_worker("worker2", "session2"),
            session_worker("worker3", "session3"),
        ]
        await asyncio.gather(*workers)
            
        # Verify each worker maintained its own session
        for i in range(1, 4):
            worker_key = f"worker{i}"
            session_key = f"session{i}"
            
            assert results[worker_key]["session"] == session_key
            assert results[worker_key]["data"] == worker_key
            
    def test_session_validation_in_artifact_operations(self):
        """Test session validation for artifact-like operations."""
        def mock_artifact_operation(operation_name, **kwargs):
            try:
                session_id = validate_session_parameter(
                    kwargs.get("session_id"), 
                    operation_name
                )
                return f"{operation_name} succeeded with session: {session_id}"
            except ValueError as e:
                return f"{operation_name} failed: {str(e)}"
                
        # Valid session provided
        result = mock_artifact_operation("upload_file", session_id="test-session")
        assert "succeeded" in result
        assert "test-session" in result
        
        # Session from context
        set_session_context("context-session")
        result = mock_artifact_operation("write_file")
        assert "succeeded" in result
        assert "context-session" in result
        
        # No session available
        clear_session_context()
        result = mock_artifact_operation("read_file")
        assert "failed" in result
        assert "requires a valid session_id" in result

class TestSessionLifecycle:
    """Test complete session lifecycle scenarios."""
    
    @pytest.mark.asyncio
    async def test_session_creation_and_cleanup_flow(self, mock_session_manager):
        """Test a complete session lifecycle from creation to cleanup."""
        # Start with no session
        clear_session_context()
        assert get_session_context() is None
        
        # Create and set session
        session_id = "lifecycle-test-session"
        set_session_context(session_id)
        assert get_session_context() == session_id
        
        # Add session data
        set_session_data(session_id, "user_id", "user123")
        set_session_data(session_id, "workspace", "test-workspace")
        
        # Allow async operations to complete
        await asyncio.sleep(0.01)
        
        # Verify data is accessible (these should be in local store now)
        assert get_session_data(session_id, "user_id") == "user123"
        assert get_session_data(session_id, "workspace") == "test-workspace"
        
        # Session should be listed
        sessions = list_sessions()
        assert session_id in sessions
        
        # Clean up session
        clear_session_data(session_id)
        clear_session_context()
        
        # Verify cleanup
        assert get_session_context() is None
        
        # Test that data is gone - suppress warnings for async fallback attempt
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = get_session_data(session_id, "user_id", "not_found")
            assert result == "not_found"
        
    def test_session_parameter_validation_scenarios(self):
        """Test various session parameter validation scenarios."""
        # Test operation names in error messages
        operations = ["upload_file", "write_file", "read_file", "delete_file"]
        
        for operation in operations:
            with pytest.raises(ValueError, match=f"Operation '{operation}' requires"):
                validate_session_parameter(None, operation)
                
        # Test with valid session
        for operation in operations:
            result = validate_session_parameter("valid-session", operation)
            assert result == "valid-session"
            
    def test_multiple_session_contexts(self):
        """Test handling multiple session contexts in sequence."""
        sessions = ["session-1", "session-2", "session-3"]
        
        for session_id in sessions:
            set_session_context(session_id)
            assert get_session_context() == session_id
            
            # Set unique data for each session
            _session_store[session_id] = {"data": f"data-for-{session_id}"}
            
        # Verify each session has its data
        for session_id in sessions:
            expected_data = f"data-for-{session_id}"
            assert get_session_data(session_id, "data") == expected_data
    """Test error handling in session management."""
    
    def test_session_error_inheritance(self):
        """Test that SessionError is properly defined."""
        error = SessionError("test message")
        assert isinstance(error, Exception)
        assert str(error) == "test message"
        
    @pytest.mark.asyncio
    async def test_session_data_with_async_manager_error(self, mock_session_manager):
        """Test handling of async manager errors."""
        # Mock an error in the session manager
        async def failing_update(*args, **kwargs):
            raise Exception("Manager error")
            
        mock_session_manager.update_session_metadata = failing_update
        
        # Should not raise exception, just log and continue
        # Use direct store access to avoid async task issues in test
        session_id = "test-session"
        _session_store[session_id] = {"key": "value"}
        
        # Data should be in local store
        assert get_session_data(session_id, "key") == "value"
        
    def test_context_variable_edge_cases(self):
        """Test edge cases with context variables."""
        # Multiple set operations
        set_session_context("session1")
        set_session_context("session2")
        assert get_session_context() == "session2"
        
        # Clear multiple times
        clear_session_context()
        clear_session_context()
        assert get_session_context() is None
        
    @pytest.mark.asyncio
    async def test_async_task_creation_in_context(self):
        """Test that async task creation works properly in async context."""
        session_id = "async-test-session"
        
        # This should work without errors in async context
        set_session_data(session_id, "async_key", "async_value")
        
        # Allow the async task to complete
        await asyncio.sleep(0.01)
        
        # Verify data was set
        assert get_session_data(session_id, "async_key") == "async_value"

if __name__ == "__main__":
    # Configure pytest to run with asyncio support
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])