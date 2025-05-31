# chuk_mcp_runtime/session/__init__.py
"""
Session management package for CHUK MCP Runtime.

This package provides session context management and session-aware tools
for maintaining state across tool calls in the MCP runtime.
"""

from chuk_mcp_runtime.session.session_management import (
    # Core session functions
    set_session_context,
    get_session_context,
    clear_session_context,
    normalize_session_id,
    require_session_context,
    get_effective_session_id,
    validate_session_parameter,
    
    # Session data management
    set_session_data,
    get_session_data,
    clear_session_data,
    list_sessions,
    
    # Decorators and context managers
    session_aware,
    SessionContext,
    
    # Exceptions
    SessionError,
)

__all__ = [
    # Core session functions
    "set_session_context",
    "get_session_context", 
    "clear_session_context",
    "normalize_session_id",
    "require_session_context",
    "get_effective_session_id",
    "validate_session_parameter",
    
    # Session data management
    "set_session_data",
    "get_session_data",
    "clear_session_data",
    "list_sessions",
    
    # Decorators and context managers
    "session_aware",
    "SessionContext",
    
    # Exceptions
    "SessionError",
]