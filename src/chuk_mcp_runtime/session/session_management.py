# chuk_mcp_runtime/session/session_management.py
"""
Session management for CHUK MCP Runtime.

This is the main session management module that provides native chuk-sessions 
integration with session context management and session-aware tools.

Usage Examples
--------------
from chuk_mcp_runtime.session.session_management import MCPSessionManager, SessionContext

session_manager = MCPSessionManager(sandbox_id="my-app")
async with SessionContext(session_manager, user_id="alice") as session_id:
    # Work within session context
    pass
"""

# Import everything from the native implementation
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
    
    # Backwards compatibility functions (these exist for legacy support)
    set_session_context,
    get_session_context,
    clear_session_context,
    validate_session_parameter,
)

# Re-export everything for clean imports
__all__ = [
    # Core session management
    "MCPSessionManager",
    "SessionContext", 
    "create_mcp_session_manager",
    
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
    
    # Legacy compatibility
    "set_session_context",
    "get_session_context",
    "clear_session_context", 
    "validate_session_parameter",
]

# Convenience factory function
def create_session_manager(sandbox_id=None, default_ttl_hours=24, auto_extend_threshold=0.1):
    """
    Create a new session manager with the given configuration.
    
    Args:
        sandbox_id: Unique identifier for this sandbox/application
        default_ttl_hours: Default session lifetime in hours
        auto_extend_threshold: Threshold for automatic session extension (0.0-1.0)
    
    Returns:
        MCPSessionManager: Configured session manager instance
    """
    return MCPSessionManager(
        sandbox_id=sandbox_id,
        default_ttl_hours=default_ttl_hours, 
        auto_extend_threshold=auto_extend_threshold
    )

# Version info
__version__ = "2.0.0"