# tests/test_session_management.py
import os
import asyncio
import pytest
import pytest_asyncio
import warnings
from unittest.mock import MagicMock, AsyncMock, patch
from contextvars import copy_context

from chuk_mcp_runtime.session import (
    # Native API
    MCPSessionManager,
    SessionContext,
    create_mcp_session_manager,
    require_session,
    get_session_or_none,
    get_user_or_none,
    with_session_auto_inject,
    session_required,
    session_optional,
    SessionError,
    SessionNotFoundError,
    SessionValidationError,
    
    # Legacy compatibility functions (now raise NotImplementedError)
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
)

class MockSessionManager:
    """Mock session manager for testing."""
    
    def __init__(self, sandbox_id="test"):
        self.sandbox_id = sandbox_id
        self.sessions_data = {}
        self.current_session = None
        self.current_user = None
        
    async def create_session(self, user_id=None, ttl_hours=24, metadata=None):
        import uuid
        session_id = f"session-{uuid.uuid4().hex[:8]}"
        self.sessions_data[session_id] = {
            "user_id": user_id,
            "ttl_hours": ttl_hours,
            "custom_metadata": metadata or {},
            "created_at": 1234567890,
            "expires_at": 1234567890 + (ttl_hours * 3600)
        }
        return session_id
        
    async def get_session_info(self, session_id):
        return self.sessions_data.get(session_id)
        
    async def validate_session(self, session_id):
        return session_id in self.sessions_data
        
    async def update_session_metadata(self, session_id, metadata):
        if session_id in self.sessions_data:
            self.sessions_data[session_id]["custom_metadata"].update(metadata)
            return True
        return False
        
    async def delete_session(self, session_id):
        return self.sessions_data.pop(session_id, None) is not None
        
    def set_current_session(self, session_id, user_id=None):
        self.current_session = session_id
        self.current_user = user_id
        
    def get_current_session(self):
        return self.current_session
        
    def get_current_user(self):
        return self.current_user
        
    def clear_context(self):
        self.current_session = None
        self.current_user = None
        
    async def auto_create_session_if_needed(self, user_id=None):
        if self.current_session and await self.validate_session(self.current_session):
            return self.current_session
        
        session_id = await self.create_session(user_id=user_id)
        self.set_current_session(session_id, user_id)
        return session_id
        
    def get_cache_stats(self):
        return {
            "cache_size": len(self.sessions_data),
            "total_sessions": len(self.sessions_data)
        }
        
    async def cleanup_expired_sessions(self):
        return 0

@pytest.fixture
async def session_manager():
    """Provide a mock session manager."""
    return MockSessionManager()

@pytest.fixture
async def real_session_manager():
    """Provide a real session manager for integration tests."""
    # Use memory provider for tests
    os.environ['SESSION_PROVIDER'] = 'memory'
    manager = MCPSessionManager(sandbox_id="test", default_ttl_hours=1)
    yield manager
    # Cleanup after test
    await manager.cleanup_expired_sessions()

class TestNativeSessionManager:
    """Test the native MCPSessionManager."""
    
    @pytest.mark.asyncio
    async def test_session_manager_creation(self):
        """Test creating a session manager."""
        manager = MCPSessionManager(sandbox_id="test-app")
        assert manager.sandbox_id == "test-app"
        assert manager.default_ttl_hours == 24
        
    @pytest.mark.asyncio
    async def test_session_manager_from_config(self):
        """Test creating session manager from config."""
        config = {
            "sessions": {
                "sandbox_id": "config-app",
                "default_ttl_hours": 8
            }
        }
        manager = create_mcp_session_manager(config)
        assert manager.sandbox_id == "config-app"
        assert manager.default_ttl_hours == 8
        
    @pytest.mark.asyncio
    async def test_session_lifecycle(self, session_manager):
        """Test complete session lifecycle."""
        # Create session
        session_id = await session_manager.create_session(
            user_id="test_user",
            metadata={"role": "admin"}
        )
        assert session_id.startswith("session-")
        
        # Validate session
        is_valid = await session_manager.validate_session(session_id)
        assert is_valid is True
        
        # Get session info
        info = await session_manager.get_session_info(session_id)
        assert info["user_id"] == "test_user"
        assert info["custom_metadata"]["role"] == "admin"
        
        # Update metadata
        success = await session_manager.update_session_metadata(
            session_id, {"last_activity": "2024-01-01"}
        )
        assert success is True
        
        # Verify update
        info = await session_manager.get_session_info(session_id)
        assert info["custom_metadata"]["last_activity"] == "2024-01-01"
        
        # Delete session
        deleted = await session_manager.delete_session(session_id)
        assert deleted is True
        
        # Verify deletion
        is_valid = await session_manager.validate_session(session_id)
        assert is_valid is False

class TestSessionContext:
    """Test the SessionContext context manager."""
    
    @pytest.mark.asyncio
    async def test_session_context_with_existing_session(self, session_manager):
        """Test SessionContext with an existing session."""
        # Create a session first
        session_id = await session_manager.create_session(user_id="test_user")
        
        async with SessionContext(session_manager, session_id=session_id) as ctx_session_id:
            assert ctx_session_id == session_id
            assert require_session() == session_id
            
        # Context should be cleared after exiting
        assert get_session_or_none() is None
        
    @pytest.mark.asyncio
    async def test_session_context_auto_create(self, session_manager):
        """Test SessionContext with auto-creation."""
        async with SessionContext(session_manager, user_id="auto_user") as session_id:
            assert session_id is not None
            assert require_session() == session_id
            
            # Verify session was created
            info = await session_manager.get_session_info(session_id)
            assert info["user_id"] == "auto_user"
            
    @pytest.mark.asyncio
    async def test_session_context_exception_handling(self, session_manager):
        """Test SessionContext handles exceptions properly."""
        session_id = await session_manager.create_session()
        session_manager.set_current_session("previous_session")
        
        try:
            async with SessionContext(session_manager, session_id=session_id):
                assert require_session() == session_id
                raise ValueError("Test exception")
        except ValueError:
            pass
            
        # Should restore previous context
        assert session_manager.get_current_session() == "previous_session"

class TestSessionHelpers:
    """Test session helper functions."""
    
    @pytest.mark.asyncio
    async def test_require_session(self, session_manager):
        """Test require_session function."""
        # Should raise when no session
        with pytest.raises(SessionError, match="No session context available"):
            require_session()
            
        # Should return session when available
        async with SessionContext(session_manager, user_id="test") as session_id:
            assert require_session() == session_id
            
    def test_get_session_or_none(self):
        """Test get_session_or_none function."""
        # Should return None when no session
        assert get_session_or_none() is None
        
        # Note: Testing with session requires async context
        
    @pytest.mark.asyncio
    async def test_get_user_or_none(self, session_manager):
        """Test get_user_or_none function."""
        # Should return None when no user
        assert get_user_or_none() is None
        
        # Should return user when available
        async with SessionContext(session_manager, user_id="test_user"):
            assert get_user_or_none() == "test_user"

class TestSessionDecorators:
    """Test session decorators."""
    
    @pytest.mark.asyncio
    async def test_session_required_decorator(self, session_manager):
        """Test @session_required decorator."""
        @session_required
        async def test_tool(data: str):
            session_id = require_session()
            return f"Processing {data} in session {session_id}"
            
        # Should fail without session
        with pytest.raises(SessionError):
            await test_tool("test_data")
            
        # Should work with session
        async with SessionContext(session_manager, user_id="test") as session_id:
            result = await test_tool("test_data")
            assert session_id in result
            assert "test_data" in result
            
    @pytest.mark.asyncio
    async def test_session_optional_decorator(self, session_manager):
        """Test @session_optional decorator."""
        @session_optional
        async def test_tool(data: str):
            session_id = get_session_or_none()
            if session_id:
                return f"Processing {data} in session {session_id}"
            else:
                return f"Processing {data} without session"
                
        # Should work without session
        result = await test_tool("test_data")
        assert "without session" in result
        
        # Should work with session
        async with SessionContext(session_manager, user_id="test") as session_id:
            result = await test_tool("test_data")
            assert session_id in result

class TestSessionAutoInjection:
    """Test automatic session injection for tools."""
    
    @pytest.mark.asyncio
    async def test_with_session_auto_inject_artifact_tool(self, session_manager):
        """Test auto-injection for artifact tools."""
        # Test with artifact tool
        args = {"filename": "test.txt", "content": "test content"}
        result = await with_session_auto_inject(session_manager, "write_file", args)
        
        assert "session_id" in result
        assert result["filename"] == "test.txt"
        assert result["content"] == "test content"
        
        # Verify session was created
        session_id = result["session_id"]
        is_valid = await session_manager.validate_session(session_id)
        assert is_valid is True
        
    @pytest.mark.asyncio
    async def test_with_session_auto_inject_non_artifact_tool(self, session_manager):
        """Test auto-injection for non-artifact tools."""
        # Test with non-artifact tool
        args = {"message": "hello"}
        result = await with_session_auto_inject(session_manager, "echo", args)
        
        # Should not add session_id for non-artifact tools
        assert "session_id" not in result
        assert result["message"] == "hello"
        
    @pytest.mark.asyncio
    async def test_with_session_auto_inject_existing_session(self, session_manager):
        """Test auto-injection when session_id already provided."""
        existing_session = await session_manager.create_session()
        
        args = {"filename": "test.txt", "session_id": existing_session}
        result = await with_session_auto_inject(session_manager, "write_file", args)
        
        # Should keep existing session_id
        assert result["session_id"] == existing_session

class TestLegacyCompatibility:
    """Test legacy function compatibility (should raise NotImplementedError)."""
    
    def test_legacy_set_session_context(self):
        """Test legacy set_session_context raises helpful error."""
        with pytest.raises(NotImplementedError, match="SessionContext or MCPSessionManager"):
            set_session_context("test-session")
            
    def test_legacy_get_session_context(self):
        """Test legacy get_session_context raises helpful error."""
        with pytest.raises(NotImplementedError, match="get_session_or_none or require_session"):
            get_session_context()
            
    def test_legacy_clear_session_context(self):
        """Test legacy clear_session_context raises helpful error."""
        with pytest.raises(NotImplementedError, match="SessionContext or MCPSessionManager"):
            clear_session_context()
            
    def test_legacy_set_session_data(self):
        """Test legacy set_session_data raises helpful error."""
        with pytest.raises(NotImplementedError, match="MCPSessionManager.update_session_metadata"):
            set_session_data("session", "key", "value")
            
    def test_legacy_get_session_data(self):
        """Test legacy get_session_data raises helpful error."""
        with pytest.raises(NotImplementedError, match="MCPSessionManager.get_session_info"):
            get_session_data("session", "key")
            
    def test_legacy_clear_session_data(self):
        """Test legacy clear_session_data raises helpful error."""
        with pytest.raises(NotImplementedError, match="MCPSessionManager.delete_session"):
            clear_session_data("session")
            
    def test_legacy_list_sessions(self):
        """Test legacy list_sessions raises helpful error."""
        with pytest.raises(NotImplementedError, match="MCPSessionManager.list_active_sessions"):
            list_sessions()
            
    def test_legacy_session_aware_decorator(self):
        """Test legacy session_aware decorator raises helpful error."""
        with pytest.raises(NotImplementedError, match="@session_required or @session_optional"):
            @session_aware(require_session=True)
            def test_func():
                pass

class TestErrorHandling:
    """Test error handling in session management."""
    
    @pytest.mark.asyncio
    async def test_session_not_found_error(self, session_manager):
        """Test SessionNotFoundError for invalid sessions."""
        # This test depends on how MCPSessionManager handles invalid sessions
        # For now, test that invalid sessions return False for validation
        is_valid = await session_manager.validate_session("invalid-session")
        assert is_valid is False
        
    @pytest.mark.asyncio
    async def test_session_validation_error(self, session_manager):
        """Test SessionValidationError scenarios."""
        # Test with invalid session in SessionContext
        with pytest.raises(SessionValidationError, match="Session .* is invalid"):
            async with SessionContext(session_manager, session_id="invalid-session", auto_create=False):
                pass

class TestIntegrationScenarios:
    """Test real-world integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_concurrent_sessions(self, session_manager):
        """Test concurrent session operations."""
        results = {}
        
        async def session_worker(worker_id, user_id):
            async with SessionContext(session_manager, user_id=user_id) as session_id:
                # Simulate some work
                await asyncio.sleep(0.01)
                
                # Update session metadata
                await session_manager.update_session_metadata(
                    session_id, {"worker_id": worker_id}
                )
                
                # Store results
                current_session = require_session()
                info = await session_manager.get_session_info(current_session)
                
                results[worker_id] = {
                    "session_id": current_session,
                    "user_id": info["user_id"],
                    "worker_id": info["custom_metadata"]["worker_id"]
                }
                
        # Run concurrent workers
        workers = [
            session_worker("worker1", "user1"),
            session_worker("worker2", "user2"),
            session_worker("worker3", "user3"),
        ]
        await asyncio.gather(*workers)
        
        # Verify each worker maintained its own session
        for i in range(1, 4):
            worker_key = f"worker{i}"
            user_key = f"user{i}"
            
            assert results[worker_key]["user_id"] == user_key
            assert results[worker_key]["worker_id"] == worker_key
            
    @pytest.mark.asyncio
    async def test_tool_session_workflow(self, session_manager):
        """Test a complete tool workflow with sessions."""
        @session_required
        async def upload_file(filename: str, content: str):
            session_id = require_session()
            # Simulate file upload
            await session_manager.update_session_metadata(
                session_id, {
                    "last_upload": filename,
                    "upload_count": 1
                }
            )
            return f"Uploaded {filename} in session {session_id}"
            
        @session_required
        async def list_files():
            session_id = require_session()
            info = await session_manager.get_session_info(session_id)
            last_upload = info["custom_metadata"].get("last_upload", "none")
            return f"Last upload in session {session_id}: {last_upload}"
            
        # Test the workflow
        async with SessionContext(session_manager, user_id="test_user") as session_id:
            # Upload a file
            result1 = await upload_file("test.txt", "content")
            assert "Uploaded test.txt" in result1
            assert session_id in result1
            
            # List files
            result2 = await list_files()
            assert "test.txt" in result2
            assert session_id in result2

class TestRealSessionManager:
    """Test with real chuk-sessions SessionManager."""
    
    @pytest.mark.asyncio
    async def test_real_session_operations(self, real_session_manager):
        """Test operations with real session manager."""
        # Create session
        session_id = await real_session_manager.create_session(
            user_id="real_user",
            metadata={"test": "data"}
        )
        
        # Validate it exists
        is_valid = await real_session_manager.validate_session(session_id)
        assert is_valid is True
        
        # Update metadata
        success = await real_session_manager.update_session_metadata(
            session_id, {"updated": True}
        )
        assert success is True
        
        # Get session info
        info = await real_session_manager.get_session_info(session_id)
        assert info is not None
        assert info["user_id"] == "real_user"
        assert info["custom_metadata"]["test"] == "data"
        assert info["custom_metadata"]["updated"] is True
        
        # Clean up
        deleted = await real_session_manager.delete_session(session_id)
        assert deleted is True

if __name__ == "__main__":
    # Configure pytest to run with asyncio support
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])