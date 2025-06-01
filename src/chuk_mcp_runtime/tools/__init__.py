"""
CHUK MCP Runtime Tools Package

This package exposes first-party tool integrations (e.g. chuk_artifacts) and
provides a thin registry/inspection layer.  Importing this module never touches
external services - registration happens only when you call the helper
functions.

**Why rewrite?**
The original file exported ``ARTIFACT_TOOLS`` as a *module-level* ``property``.
``property`` only works on classes, so any code that did
``len(ARTIFACT_TOOLS)`` raised ``TypeError: object of type 'property' has no
len()``.  This version keeps a lazy helper but exports an ordinary list value
that is always safe to introspect.
"""

from __future__ import annotations

from typing import Any, Dict, List

# --------------------------------------------------------------------------- #
#  Optional chuk_artifacts integration                                       #
# --------------------------------------------------------------------------- #

try:
    from .artifacts_tools import (
        register_artifacts_tools,
        get_artifacts_tools_info,
        get_enabled_tools,
        configure_artifacts_tools,
        ALL_ARTIFACT_TOOLS,
        CHUK_ARTIFACTS_AVAILABLE,
    )

    ARTIFACTS_TOOLS_AVAILABLE: bool = True

except ImportError:  # chuk_artifacts (or its wrapper) missing
    # Fallback stubs keep the public API stable even when the optional
    # dependency is absent.
    ARTIFACTS_TOOLS_AVAILABLE = False
    CHUK_ARTIFACTS_AVAILABLE = False
    ALL_ARTIFACT_TOOLS: List[str] = []

    async def register_artifacts_tools(
        config: Dict[str, Any] | None = None,
    ) -> bool:  # noqa: D401
        """Placeholder - returns False when artifacts support is unavailable."""
        return False

    def get_artifacts_tools_info() -> Dict[str, Any]:  # noqa: D401
        """Return an empty-info structure when artifacts support is unavailable."""
        return {
            "available": False,
            "configured": False,
            "enabled_tools": [],
            "disabled_tools": [],
            "total_tools": 0,
            "enabled_count": 0,
            "config": {},
            "install_command": "pip install chuk-artifacts",
        }

    def get_enabled_tools() -> List[str]:  # noqa: D401
        return []

    def configure_artifacts_tools(config: Dict[str, Any]) -> None:  # noqa: D401
        pass


# --------------------------------------------------------------------------- #
#  Convenience helpers                                                       #
# --------------------------------------------------------------------------- #

def get_artifact_tools() -> List[str]:
    """Return the list of *currently* enabled artifact tools."""
    return get_enabled_tools()


# Snapshot at import time so callers can safely do ``len(ARTIFACT_TOOLS)``.
# If you enable/disable tools after import, call ``get_artifact_tools()`` for
# a live value.
ARTIFACT_TOOLS: List[str] = get_enabled_tools()


# --------------------------------------------------------------------------- #
#  Composite registration helpers - future extension point                   #
# --------------------------------------------------------------------------- #

async def register_all_tools(config: Dict[str, Any] | None = None) -> Dict[str, bool]:
    """Register every tool family known to this package."""
    results: Dict[str, bool] = {}

    # Artifacts
    if ARTIFACTS_TOOLS_AVAILABLE:
        results["artifacts"] = await register_artifacts_tools(config)
    else:
        results["artifacts"] = False

    # TODO: add more tool families here when they exist.

    return results


def get_all_tools_info(config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return a structured overview of every tool family."""
    return {
        "artifacts": get_artifacts_tools_info(),
        "total_enabled": len(get_enabled_tools()),
        "categories": ["artifacts"],
    }


# --------------------------------------------------------------------------- #
#  Re-export public symbols (so * import works)                              #
# --------------------------------------------------------------------------- #

__all__ = [
    # Registration helpers
    "register_artifacts_tools",
    "register_all_tools",
    # Information helpers
    "get_artifacts_tools_info",
    "get_all_tools_info",
    "get_enabled_tools",
    # Configuration
    "configure_artifacts_tools",
    # Tool lists
    "ALL_ARTIFACT_TOOLS",
    "ARTIFACT_TOOLS",
    # Availability flags
    "ARTIFACTS_TOOLS_AVAILABLE",
    "CHUK_ARTIFACTS_AVAILABLE",
    # Convenience
    "get_artifact_tools",
]
