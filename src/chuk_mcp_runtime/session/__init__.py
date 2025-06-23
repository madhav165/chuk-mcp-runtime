# chuk_mcp_runtime/session/__init__.py
"""
Session management package for CHUK MCP Runtime.

This package provides native chuk-sessions integration with session context 
management and session-aware tools for maintaining state across tool calls 
in the MCP runtime.

Migration from Bridge to Native
-------------------------------
This package now uses chuk-sessions directly instead of the bridge pattern.
Legacy functions raise NotImplementedError with helpful migration guidance.

Usage Examples
--------------
# Native API (recommended)
from chuk_mcp_runtime.session import MCPSessionManager, SessionContext

session_manager = MCPSessionManager(sandbox_id="my-app")
async with SessionContext(session_manager, user_id="alice") as session_id:
    # Work within session context
    pass
"""

# Import native session management components
from chuk_mcp_runtime.session.native_session_management import (
    # Core native classes
    MCPSessionManager,
    SessionContext,
    create_mcp_session_manager,
    
    # Context helpers
    require_session,
    get_session_or_none,
    get_user_or_none,
    
    # Tool integration
    with_session_auto_inject,
    session_required,
    session_optional,
    
    # Exceptions
    SessionError,
    SessionNotFoundError,
    SessionValidationError,
)

# ───────────────────────── Legacy Compatibility Stubs ─────────────────────

def set_session_context(session_id: str):
    """
    REMOVED: Legacy session context management.
    
    MIGRATION: Use SessionContext instead:
    
    # Old
    set_session_context("session-123")
    try:
        # do work
    finally:
        clear_session_context()
    
    # New
    async with SessionContext(session_manager, session_id="session-123"):
        # do work - automatic cleanup
    """
    raise NotImplementedError(
        "set_session_context has been removed. Use SessionContext instead.\n"
        "See migration guide: async with SessionContext(session_manager, session_id='...'):"
    )

def get_session_context():
    """
    REMOVED: Legacy session context retrieval.
    
    MIGRATION: Use get_session_or_none() or require_session() instead:
    
    # Old
    session_id = get_session_context()
    
    # New
    session_id = get_session_or_none()  # Returns None if no session
    # or
    session_id = require_session()     # Raises error if no session
    """
    raise NotImplementedError(
        "get_session_context has been removed. Use get_session_or_none() or require_session() instead."
    )

def clear_session_context():
    """
    REMOVED: Legacy session context clearing.
    
    MIGRATION: Use SessionContext which automatically clears on exit:
    
    # Old
    clear_session_context()
    
    # New - SessionContext automatically clears
    async with SessionContext(session_manager, ...):
        pass  # automatically cleared on exit
    """
    raise NotImplementedError(
        "clear_session_context has been removed. Use SessionContext which automatically clears on exit."
    )

def normalize_session_id(session_id: str) -> str:
    """
    Legacy compatibility function - basic validation only.
    
    MIGRATION: Use MCPSessionManager.validate_session() for full validation.
    """
    if not session_id or not session_id.strip():
        raise SessionError("Session ID cannot be empty")
    return session_id.strip()

def require_session_context() -> str:
    """
    Legacy compatibility function.
    
    MIGRATION: Use require_session() instead.
    """
    session_id = get_session_or_none()
    if not session_id:
        raise SessionError("No session context available")
    return session_id

def get_effective_session_id(provided_session: str = None) -> str:
    """
    Legacy compatibility function.
    
    MIGRATION: Use session_id or require_session() pattern instead.
    """
    if provided_session:
        return normalize_session_id(provided_session)
    session_id = get_session_or_none()
    if session_id:
        return session_id
    raise SessionError("No session_id provided and none in context")

def validate_session_parameter(session_id: str = None, operation: str = "unknown") -> str:
    """
    Legacy compatibility function.
    
    MIGRATION: Use session_id or require_session() pattern instead:
    
    # Old
    effective_session = validate_session_parameter(session_id, "my_operation")
    
    # New
    effective_session = session_id or require_session()
    """
    return get_effective_session_id(session_id)

def set_session_data(session_id: str, key: str, value: any) -> None:
    """
    REMOVED: Legacy session data management.
    
    MIGRATION: Use MCPSessionManager.update_session_metadata() instead:
    
    # Old
    set_session_data(session_id, "key", "value")
    
    # New
    await session_manager.update_session_metadata(session_id, {"key": "value"})
    """
    raise NotImplementedError(
        "set_session_data has been removed. Use MCPSessionManager.update_session_metadata() instead."
    )

def get_session_data(session_id: str, key: str, default: any = None) -> any:
    """
    REMOVED: Legacy session data management.
    
    MIGRATION: Use MCPSessionManager.get_session_info() instead:
    
    # Old
    value = get_session_data(session_id, "key")
    
    # New
    info = await session_manager.get_session_info(session_id)
    value = info['custom_metadata'].get("key")
    """
    raise NotImplementedError(
        "get_session_data has been removed. Use MCPSessionManager.get_session_info() instead."
    )

def clear_session_data(session_id: str) -> None:
    """
    REMOVED: Legacy session data management.
    
    MIGRATION: Use MCPSessionManager.delete_session() instead:
    
    # Old
    clear_session_data(session_id)
    
    # New
    await session_manager.delete_session(session_id)
    """
    raise NotImplementedError(
        "clear_session_data has been removed. Use MCPSessionManager.delete_session() instead."
    )

def list_sessions() -> list[str]:
    """
    REMOVED: Legacy session listing.
    
    MIGRATION: Use MCPSessionManager.list_active_sessions() instead:
    
    # Old
    sessions = list_sessions()
    
    # New
    sessions_info = await session_manager.list_active_sessions()
    """
    raise NotImplementedError(
        "list_sessions has been removed. Use MCPSessionManager.list_active_sessions() instead."
    )

def session_aware(require_session: bool = True):
    """
    REMOVED: Legacy session decorator.
    
    MIGRATION: Use @session_required or @session_optional instead:
    
    # Old
    @session_aware(require_session=True)
    def my_tool():
        pass
    
    # New
    @session_required
    def my_tool():
        pass
    """
    raise NotImplementedError(
        "session_aware decorator has been removed. Use @session_required or @session_optional instead."
    )

# ───────────────────────── Utility Functions ─────────────────────────────

def get_migration_status() -> dict:
    """Get information about the migration status."""
    return {
        "native_available": True,
        "legacy_available": False,
        "recommended_api": "native",
        "migration_complete": True,
        "version": "2.0.0-native"
    }

def create_session_manager_from_config(config: dict = None) -> MCPSessionManager:
    """
    Convenience function to create session manager from config.
    
    This is the preferred way to create session managers in new code.
    """
    return create_mcp_session_manager(config)

# ───────────────────────── Public API ─────────────────────────────────

__all__ = [
    # ========================================================================
    # NATIVE API (Recommended for new code)
    # ========================================================================
    
    # Core classes
    "MCPSessionManager",
    "SessionContext", 
    "create_mcp_session_manager",
    "create_session_manager_from_config",
    
    # Context functions
    "require_session",
    "get_session_or_none",
    "get_user_or_none",
    
    # Tool integration
    "with_session_auto_inject",
    "session_required",
    "session_optional",
    
    # Exceptions
    "SessionError",
    "SessionNotFoundError",
    "SessionValidationError",
    
    # ========================================================================
    # LEGACY COMPATIBILITY (Raises NotImplementedError with migration help)
    # ========================================================================
    
    # Legacy context functions
    "set_session_context",
    "get_session_context", 
    "clear_session_context",
    "normalize_session_id",
    "require_session_context",
    "get_effective_session_id",
    "validate_session_parameter",
    
    # Legacy data management
    "set_session_data",
    "get_session_data",
    "clear_session_data", 
    "list_sessions",
    
    # Legacy decorators
    "session_aware",
    
    # ========================================================================
    # UTILITIES
    # ========================================================================
    
    "get_migration_status",
]

# ───────────────────────── Version Info ─────────────────────────────────

__version__ = "2.0.0"
__api_version__ = "native"
__legacy_support__ = False