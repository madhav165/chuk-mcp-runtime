# chuk_mcp_runtime/session/session_management.py
"""
Session helpers for chuk_mcp_runtime **v2**

• ContextVar → cheap “current call” session_id.
• All registry / TTL / metadata operations delegate to a singleton
  ``SessionManager`` (imported lazily to avoid circular imports).
• Public API stays identical to the legacy version so nothing else
  in the runtime has to change.

If you want the full manager directly:

>>> from chuk_mcp_runtime.session.session_bridge import get_session_manager
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional

from chuk_mcp_runtime.server.logging_config import get_logger

logger = get_logger("chuk_mcp_runtime.session")

# ───────────────────────── ContextVar pocket ──────────────────────────
_session_ctx: ContextVar[Optional[str]] = ContextVar("session_context", default=None)

# ultra-fast scratch data (kept for legacy callers)
_session_store: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------
#  INTERNAL helper – lazy import to break circular dependency           
# ---------------------------------------------------------------------

def _mgr():  # noqa: D401
    """Return the shared SessionManager (imported only when needed)."""
    from chuk_mcp_runtime.session.session_bridge import get_session_manager  # local import!

    return get_session_manager()


# ───────────────────────── exception type ─────────────────────────────
class SessionError(Exception):
    """Raised when session operations fail."""


# ───────────────────────── basic helpers ──────────────────────────────

def set_session_context(session_id: str) -> None:
    if not session_id or not session_id.strip():
        raise SessionError("Session ID cannot be empty")
    _session_ctx.set(session_id.strip())
    logger.debug("Session context set → %s", session_id)


def get_session_context() -> Optional[str]:
    return _session_ctx.get()


def clear_session_context() -> None:
    _session_ctx.set(None)
    logger.debug("Session context cleared")


# ───────────────────────── legacy-compat API  ─────────────────────────
_allowed_chars = re.compile(r"[A-Za-z0-9_.-]+")


def normalize_session_id(session_id: str) -> str:
    """Validate/clean session_id (≤100 chars, safe charset)."""
    if not session_id:
        raise SessionError("Session ID cannot be None or empty")
    sid = session_id.strip()
    if not sid:
        raise SessionError("Session ID cannot be empty after normalization")
    if len(sid) > 100:
        raise SessionError("Session ID too long (max 100 characters)")
    if not _allowed_chars.fullmatch(sid):
        raise SessionError("Session ID contains invalid characters")
    return sid


def require_session_context() -> str:
    sid = get_session_context()
    if not sid:
        raise SessionError("No session context available")
    return sid


def get_effective_session_id(provided_session: Optional[str] = None) -> str:
    if provided_session:
        return normalize_session_id(provided_session)
    ctx = get_session_context()
    if ctx:
        return ctx
    raise SessionError("No session_id provided and none in context")


def validate_session_parameter(session_id: Optional[str], operation: str) -> str:
    try:
        return get_effective_session_id(session_id)
    except SessionError as exc:
        raise ValueError(
            f"Operation '{operation}' requires a valid session_id: {exc}"
        ) from None


# ───────────────────────── registry → SessionManager ──────────────────

def list_sessions() -> list[str]:
    mgr_ids = list(_mgr()._session_cache.keys())  # type: ignore[attr-defined]
    legacy_ids = list(_session_store.keys())
    return sorted(set(mgr_ids) | set(legacy_ids))


def set_session_data(session_id: str, key: str, value: Any) -> None:
    _session_store.setdefault(session_id, {})[key] = value

    async def _push():
        try:
            await _mgr().update_session_metadata(session_id, {key: value})
        except Exception as exc:  # noqa: BLE001
            logger.debug("SessionManager metadata update failed: %s", exc)

    asyncio.create_task(_push())


def get_session_data(session_id: str, key: str, default: Any = None) -> Any:
    if session_id in _session_store and key in _session_store[session_id]:
        return _session_store[session_id][key]

    async def _pull():
        info = await _mgr().get_session_info(session_id)
        return (info or {}).get("custom_metadata", {}).get(key, default)

    try:
        return asyncio.run(_pull())
    except RuntimeError:  # already in event loop → schedule task & return default
        asyncio.create_task(_pull())
        return default


def clear_session_data(session_id: str) -> None:
    _session_store.pop(session_id, None)
    asyncio.create_task(_mgr().delete_session(session_id))


# ───────────────────────── decorator for tools ────────────────────────

def session_aware(require_session: bool = True):
    """Decorate a tool to enforce session context at call-time."""

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            if require_session and not get_session_context():
                raise ValueError(
                    f"Tool '{func.__name__}' requires session context. "
                    "Please set session context first."
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ───────────────────────── async context helper ───────────────────────

class SessionContext:  # noqa: D401
    """Async context-manager to temporarily set session_id for the task."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.previous: Optional[str] = None

    async def __aenter__(self):
        self.previous = get_session_context()
        set_session_context(self.session_id)
        return self

    async def __aexit__(self, *_):
        set_session_context(self.previous) if self.previous else clear_session_context()


# ───────────────────────── misc helpers kept for API ──────────────────

def list_sessions_cache_stats() -> Dict[str, Any]:
    return _mgr().get_cache_stats()


async def cleanup_expired_sessions() -> int:
    return await _mgr().cleanup_expired_sessions()