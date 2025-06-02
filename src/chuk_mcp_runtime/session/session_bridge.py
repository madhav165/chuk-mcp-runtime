# chuk_mcp_runtime/session/session_bridge.py
"""
Lazy, drop-in access to a shared ``chuk_sessions.SessionManager``.

• Keeps the ContextVar helper from ``session_management`` available via
  re-export so callers can just import *everything* from this one module.
• Delegates registry/TTL work to the singleton SessionManager.
"""

from __future__ import annotations

import os
from typing import Optional

from chuk_sessions.session_manager import SessionManager

# re‑export ContextVar helpers for convenience ------------------------------
from chuk_mcp_runtime.session.session_management import (
    set_session_context,   # noqa: F401  (re‑export)
    SessionContext,        # noqa: F401  (re‑export)
)

__all__ = [
    "get_session_manager",
    "allocate_session",
    "validate_session",
    "get_session_info",
    "update_session_metadata",
    "extend_session_ttl",
    "delete_session",
    "get_canonical_prefix",
    "generate_artifact_key",
    "parse_grid_key",
    "get_cache_stats",
    "cleanup_expired_sessions",
    # re‑exported helpers
    "set_session_context",
    "SessionContext",
]

# ───────────────────────── singleton ──────────────────────────
_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:  # noqa: D401
    """Return (and lazily create) the shared :class:`SessionManager`.

    Priority for sandbox detection:
        2. CHUK_SANDBOX_ID     - convenience alias
        3. MCP_SANDBOX_ID      - legacy name kept for back-compat
        4. "mcp-runtime"       - library default
    """
    global _manager
    if _manager is None:
        sandbox = (
            os.getenv("SANDBOX_ID")
            or os.getenv("CHUK_SANDBOX_ID")
            or os.getenv("MCP_SANDBOX_ID")
            or "mcp-runtime"
        )
        _manager = SessionManager(sandbox_id=sandbox)
    return _manager



# ─────────────────────── convenience aliases ───────────────────────

async def allocate_session(**kw) -> str:  # noqa: D401
    return await get_session_manager().allocate_session(**kw)


async def validate_session(session_id: str) -> bool:  # noqa: D401
    return await get_session_manager().validate_session(session_id)


async def get_session_info(session_id: str):
    return await get_session_manager().get_session_info(session_id)


async def update_session_metadata(session_id: str, data: dict[str, object]):
    return await get_session_manager().update_session_metadata(session_id, data)


async def extend_session_ttl(session_id: str, additional_hours: int):
    return await get_session_manager().extend_session_ttl(session_id, additional_hours)


async def delete_session(session_id: str) -> bool:
    return await get_session_manager().delete_session(session_id)


def get_canonical_prefix(session_id: str) -> str:
    return get_session_manager().get_canonical_prefix(session_id)


def generate_artifact_key(session_id: str, artifact_id: str) -> str:
    return get_session_manager().generate_artifact_key(session_id, artifact_id)


def parse_grid_key(grid_key: str):
    return get_session_manager().parse_grid_key(grid_key)


def get_cache_stats():
    return get_session_manager().get_cache_stats()


async def cleanup_expired_sessions() -> int:
    return await get_session_manager().cleanup_expired_sessions()
