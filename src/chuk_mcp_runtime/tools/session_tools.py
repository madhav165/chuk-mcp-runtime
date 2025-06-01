# chuk_mcp_runtime/tools/session_tools.py
"""
Session Management Tools for CHUK MCP Runtime

This module provides MCP tools for managing session context and state.
These tools allow clients to manage their session lifecycle directly.
"""

from typing import Dict, Any, Optional
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool, TOOLS_REGISTRY
from chuk_mcp_runtime.session.session_management import (
    get_session_context,
    set_session_context,
    normalize_session_id,
    clear_session_context,
    list_sessions,
    get_session_data,
    set_session_data,
    SessionError
)
from chuk_mcp_runtime.server.logging_config import get_logger

logger = get_logger("chuk_mcp_runtime.tools.session")

# Default configuration for session tools
DEFAULT_SESSION_TOOLS_CONFIG = {
    "enabled": False,  # Disabled by default - must be explicitly enabled
    "tools": {
        "get_current_session": {
            "enabled": False,  # Disabled by default
            "description": "Get information about the current session context"
        },
        "set_session": {
            "enabled": False,  # Disabled by default
            "description": "Set the session context for subsequent operations"
        },
        "clear_session": {
            "enabled": False,  # Disabled by default
            "description": "Clear the current session context"
        },
        "list_sessions": {
            "enabled": False,  # Disabled by default
            "description": "List all active sessions"
        },
        "get_session_info": {
            "enabled": False,  # Disabled by default
            "description": "Get detailed information about a specific session"
        },
        "create_session": {
            "enabled": False,  # Disabled by default
            "description": "Create a new session with optional metadata"
        }
    }
}

# Global configuration state
_session_tools_config: Dict[str, Any] = {}
_enabled_session_tools: set = set()


def configure_session_tools(config: Dict[str, Any]) -> None:
    """Configure session tools based on configuration."""
    global _session_tools_config, _enabled_session_tools
    
    # Get session tools configuration
    _session_tools_config = config.get("session_tools", DEFAULT_SESSION_TOOLS_CONFIG)
    
    # Clear enabled tools
    _enabled_session_tools.clear()
    
    # Check if session tools are enabled globally
    if not _session_tools_config.get("enabled", True):
        logger.info("Session tools disabled in configuration")
        return
    
    # Process individual tool configuration
    tools_config = _session_tools_config.get("tools", DEFAULT_SESSION_TOOLS_CONFIG["tools"])
    
    for tool_name, tool_config in tools_config.items():
        if tool_config.get("enabled", True):
            _enabled_session_tools.add(tool_name)
            logger.debug(f"Enabled session tool: {tool_name}")
        else:
            logger.debug(f"Disabled session tool: {tool_name}")
    
    logger.info(f"Configured {len(_enabled_session_tools)} session tools: {', '.join(sorted(_enabled_session_tools))}")


def is_session_tool_enabled(tool_name: str) -> bool:
    """Check if a specific session tool is enabled."""
    return tool_name in _enabled_session_tools


# ============================================================================
# Session Management Tools
# ============================================================================

@mcp_tool(name="get_current_session", description="Get information about the current session context")
async def get_current_session() -> Dict[str, Any]:
    """
    Get information about the current session.
    
    Returns:
        Dictionary containing current session information including:
        - session_id: Current session ID or None
        - status: 'active' if session exists, 'no_session' if not
        - message: Human-readable status message
    """
    current_session = get_session_context()
    
    if current_session:
        return {
            "session_id": current_session,
            "status": "active",
            "message": f"Current session: {current_session}"
        }
    else:
        return {
            "session_id": None,
            "status": "no_session",
            "message": "No session context available. A session will be auto-created when needed."
        }


@mcp_tool(name="set_session", description="Set the session context for subsequent operations")
async def set_session_context_tool(session_id: str) -> str:
    """
    Set the session context for subsequent operations.
    
    Args:
        session_id: Session ID to use for subsequent operations.
                   Must be a valid session ID (alphanumeric, dots, underscores, hyphens)
        
    Returns:
        Success message confirming the session was set
        
    Raises:
        ValueError: If the session ID is invalid or cannot be set
    """
    try:
        normalized_id = normalize_session_id(session_id)
        set_session_context(normalized_id)
        return f"Session context set to: {normalized_id}"
    except SessionError as e:
        raise ValueError(f"Failed to set session context: {str(e)}")
    except Exception as e:
        raise ValueError(f"Failed to set session context: {str(e)}")


@mcp_tool(name="clear_session", description="Clear the current session context")
async def clear_session_context_tool() -> str:
    """
    Clear the current session context.
    
    Returns:
        Success message confirming the session was cleared
    """
    previous_session = get_session_context()
    clear_session_context()
    
    if previous_session:
        return f"Session context cleared (was: {previous_session})"
    else:
        return "Session context cleared (no previous session)"


@mcp_tool(name="list_sessions", description="List all active sessions")
async def list_sessions_tool() -> Dict[str, Any]:
    """
    List all active sessions.
    
    Returns:
        Dictionary containing:
        - sessions: List of active session IDs
        - count: Number of active sessions
        - current_session: Current session ID if any
    """
    sessions = list_sessions()
    current = get_session_context()
    
    return {
        "sessions": sessions,
        "count": len(sessions),
        "current_session": current
    }


@mcp_tool(name="get_session_info", description="Get detailed information about a specific session")
async def get_session_info_tool(session_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific session.
    
    Args:
        session_id: Session ID to get information about
        
    Returns:
        Dictionary containing session information and metadata
    """
    try:
        normalized_id = normalize_session_id(session_id)
        
        # Get basic session info
        is_current = get_session_context() == normalized_id
        
        # Try to get some session data (this is a simple example)
        # In a real implementation, you might have more sophisticated session metadata
        sessions = list_sessions()
        exists = normalized_id in sessions
        
        result = {
            "session_id": normalized_id,
            "exists": exists,
            "is_current": is_current,
            "status": "active" if exists else "not_found"
        }
        
        if exists:
            # Try to get some session metadata
            try:
                # This is a simple example - you could extend this to get more session info
                result["metadata"] = {
                    "created_via": "mcp_session_tools",
                    "last_accessed": "unknown"  # Could be enhanced with actual tracking
                }
            except Exception:
                result["metadata"] = {}
        
        return result
        
    except SessionError as e:
        raise ValueError(f"Invalid session ID: {str(e)}")


@mcp_tool(name="create_session", description="Create a new session with optional metadata")
async def create_session_tool(
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a new session with optional metadata.
    
    Args:
        session_id: Optional session ID. If not provided, a unique ID will be generated
        metadata: Optional metadata to associate with the session
        
    Returns:
        Dictionary containing information about the created session
    """
    import uuid
    import time
    
    # Generate session ID if not provided
    if session_id is None:
        timestamp = int(time.time())
        random_suffix = str(uuid.uuid4().hex)[:8]
        session_id = f"session-{timestamp}-{random_suffix}"
    
    try:
        normalized_id = normalize_session_id(session_id)
        
        # Set the session context
        set_session_context(normalized_id)
        
        # Store metadata if provided
        if metadata:
            for key, value in metadata.items():
                set_session_data(normalized_id, key, value)
        
        # Add creation metadata
        creation_meta = {
            "created_at": time.time(),
            "created_via": "mcp_session_tools"
        }
        
        for key, value in creation_meta.items():
            set_session_data(normalized_id, key, value)
        
        return {
            "session_id": normalized_id,
            "status": "created",
            "is_current": True,
            "metadata": {**(metadata or {}), **creation_meta}
        }
        
    except SessionError as e:
        raise ValueError(f"Failed to create session: {str(e)}")


# ============================================================================
# Registration Functions
# ============================================================================

async def register_session_tools(config: Dict[str, Any] = None) -> bool:
    """Register session management tools with the MCP runtime."""
    
    # Configure tools based on config
    if config:
        configure_session_tools(config)
    else:
        # Use default configuration
        configure_session_tools(DEFAULT_SESSION_TOOLS_CONFIG)
    
    if not _enabled_session_tools:
        logger.info("No session tools enabled in configuration")
        return False
    
    # Initialize the tool registry to ensure decorators are processed
    from chuk_mcp_runtime.common.mcp_tool_decorator import initialize_tool_registry
    await initialize_tool_registry()
    
    # Map of available session tools - they should now have _mcp_tool metadata
    available_tools = {
        "get_current_session": get_current_session,
        "set_session": set_session_context_tool,
        "clear_session": clear_session_context_tool,
        "list_sessions": list_sessions_tool,
        "get_session_info": get_session_info_tool,
        "create_session": create_session_tool,
    }
    
    # Register enabled tools
    registered_count = 0
    for tool_name in _enabled_session_tools:
        if tool_name in available_tools:
            tool_func = available_tools[tool_name]
            
            # Check if tool needs initialization
            if hasattr(tool_func, '_needs_init') and tool_func._needs_init:
                logger.debug(f"Initializing session tool: {tool_name}")
                # The tool should have been initialized by initialize_tool_registry()
                # Let's check if it's in the global registry now
                from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY as GLOBAL_REGISTRY
                if tool_name in GLOBAL_REGISTRY:
                    tool_func = GLOBAL_REGISTRY[tool_name]
                
            # Verify the tool has proper metadata after initialization
            if hasattr(tool_func, '_mcp_tool'):
                TOOLS_REGISTRY[tool_name] = tool_func
                registered_count += 1
                logger.debug(f"Registered session tool: {tool_name}")
            else:
                logger.warning(f"Session tool {tool_name} still missing _mcp_tool metadata after initialization")
                
                # Manual fallback - create the decorator manually
                tool_config = DEFAULT_SESSION_TOOLS_CONFIG["tools"].get(tool_name, {})
                description = tool_config.get("description", f"Session tool: {tool_name}")
                
                # Apply the decorator manually and initialize immediately
                try:
                    decorated_func = mcp_tool(name=tool_name, description=description)(tool_func)
                    
                    # Force initialization if needed
                    if hasattr(decorated_func, '_needs_init') and decorated_func._needs_init:
                        from chuk_mcp_runtime.common.mcp_tool_decorator import _initialize_tool
                        await _initialize_tool(tool_name, decorated_func)
                        # Get the initialized version
                        if tool_name in TOOLS_REGISTRY:
                            decorated_func = TOOLS_REGISTRY[tool_name]
                    
                    TOOLS_REGISTRY[tool_name] = decorated_func
                    registered_count += 1
                    logger.debug(f"Registered session tool with manual initialization: {tool_name}")
                except Exception as e:
                    logger.error(f"Failed to register session tool {tool_name}: {e}")
    
    logger.info(f"Registered {registered_count} session management tools")
    logger.info(f"Enabled session tools: {', '.join(sorted(_enabled_session_tools))}")
    
    return registered_count > 0


def get_session_tools_info() -> Dict[str, Any]:
    """Get information about available and configured session tools."""
    all_tools = list(DEFAULT_SESSION_TOOLS_CONFIG["tools"].keys())
    
    return {
        "available": True,  # Session tools are always available
        "configured": bool(_session_tools_config),
        "enabled_tools": list(_enabled_session_tools),
        "disabled_tools": [t for t in all_tools if t not in _enabled_session_tools],
        "total_tools": len(all_tools),
        "enabled_count": len(_enabled_session_tools),
        "config": _session_tools_config
    }


def get_enabled_session_tools() -> list[str]:
    """Get list of currently enabled session tools."""
    return list(_enabled_session_tools)