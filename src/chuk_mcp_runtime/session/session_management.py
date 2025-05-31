# chuk_mcp_runtime/session/session_management.py
"""
Session management support for CHUK MCP Runtime.

Provides session context management that can be used by MCP servers
to maintain session state across tool calls.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Optional, Dict, Any, Callable

from chuk_mcp_runtime.server.logging_config import get_logger

logger = get_logger("chuk_mcp_runtime.session")

# Global context variable for session tracking across async boundaries
_session_context: ContextVar[Optional[str]] = ContextVar('session_context', default=None)

# Store for session-specific data
_session_store: Dict[str, Dict[str, Any]] = {}


class SessionError(Exception):
    """Raised when session operations fail."""
    pass


def set_session_context(session_id: str) -> None:
    """
    Set the current session context for the async task.
    
    Args:
        session_id: The session identifier to set
        
    Raises:
        SessionError: If session_id is invalid
    """
    if not session_id or not session_id.strip():
        raise SessionError("Session ID cannot be empty")
    
    normalized_session = normalize_session_id(session_id)
    _session_context.set(normalized_session)
    logger.debug(f"Session context set to: {normalized_session}")


def get_session_context() -> Optional[str]:
    """
    Get the current session context.
    
    Returns:
        The current session ID or None if not set
    """
    return _session_context.get()


def clear_session_context() -> None:
    """Clear the current session context."""
    _session_context.set(None)
    logger.debug("Session context cleared")


def normalize_session_id(session_id: str) -> str:
    """
    Normalize session ID format for consistency.
    
    Args:
        session_id: Raw session ID
        
    Returns:
        Normalized session ID
        
    Raises:
        SessionError: If session ID is invalid
    """
    if not session_id:
        raise SessionError("Session ID cannot be None or empty")
    
    # Remove whitespace and ensure valid format
    normalized = session_id.strip()
    
    if not normalized:
        raise SessionError("Session ID cannot be empty after normalization")
    
    # Additional validation (customize as needed)
    if len(normalized) > 100:
        raise SessionError("Session ID too long (max 100 characters)")
    
    # Ensure alphanumeric plus limited special chars
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if not all(c in allowed_chars for c in normalized):
        raise SessionError("Session ID contains invalid characters")
    
    return normalized


def require_session_context() -> str:
    """
    Get session context, raising error if not set.
    
    Returns:
        Current session ID
        
    Raises:
        SessionError: If no session context is available
    """
    session_id = get_session_context()
    if not session_id:
        raise SessionError(
            "No session context available. All operations require a valid session ID."
        )
    return session_id


def get_effective_session_id(provided_session: Optional[str] = None) -> str:
    """
    Get effective session ID with strict enforcement.
    
    Priority:
    1. Explicitly provided session_id parameter
    2. Current session context
    3. ERROR - no fallback allowed
    
    Args:
        provided_session: Optional explicit session ID
        
    Returns:
        Effective session ID to use
        
    Raises:
        SessionError: If no session is available
    """
    if provided_session:
        return normalize_session_id(provided_session)
    
    context_session = get_session_context()
    if context_session:
        return context_session
    
    raise SessionError(
        "No session ID provided and no session context available. "
        "All operations require explicit session identification."
    )


# Session store operations
def set_session_data(session_id: str, key: str, value: Any) -> None:
    """
    Store data for a specific session.
    
    Args:
        session_id: Session identifier
        key: Data key
        value: Data value
    """
    if session_id not in _session_store:
        _session_store[session_id] = {}
    _session_store[session_id][key] = value


def get_session_data(session_id: str, key: str, default: Any = None) -> Any:
    """
    Get data for a specific session.
    
    Args:
        session_id: Session identifier
        key: Data key
        default: Default value if not found
        
    Returns:
        Stored value or default
    """
    return _session_store.get(session_id, {}).get(key, default)


def clear_session_data(session_id: str) -> None:
    """
    Clear all data for a specific session.
    
    Args:
        session_id: Session identifier
    """
    _session_store.pop(session_id, None)


def list_sessions() -> list[str]:
    """
    List all active sessions.
    
    Returns:
        List of session IDs
    """
    return list(_session_store.keys())


# Decorator for session-aware tools
def session_aware(require_session: bool = True):
    """
    Decorator to make tools session-aware.
    
    Args:
        require_session: Whether to require a session context
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            if require_session:
                session_id = get_session_context()
                if not session_id:
                    raise ValueError(
                        f"Tool '{func.__name__}' requires session context. "
                        f"Please set session context first."
                    )
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Context manager for temporary session setting
class SessionContext:
    """Context manager for setting temporary session context."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.previous_session = None
    
    async def __aenter__(self):
        self.previous_session = get_session_context()
        set_session_context(self.session_id)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.previous_session:
            set_session_context(self.previous_session)
        else:
            clear_session_context()


# Session validation utilities
def validate_session_parameter(session_id: Optional[str], operation: str) -> str:
    """
    Validate session ID parameter with helpful error messages.
    
    Args:
        session_id: Provided session ID (may be None)
        operation: Name of operation for error messages
        
    Returns:
        Valid session ID
        
    Raises:
        ValueError: If session validation fails
    """
    try:
        return get_effective_session_id(session_id)
    except SessionError as e:
        # Use ValueError instead of McpError to avoid constructor issues
        raise ValueError(f"Operation '{operation}' requires a valid session_id: {e}")