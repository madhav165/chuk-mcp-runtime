# -*- coding: utf-8 -*-
# chuk_mcp_runtime/artifacts/__init__.py
"""
Backward compatibility layer for chuk_artifacts.

This module provides a thin compatibility layer that exposes chuk_artifacts
functionality while maintaining the existing chuk_mcp_runtime.artifacts API.

Migration Path
--------------
Old code using chuk_mcp_runtime.artifacts will continue to work:
>>> from chuk_mcp_runtime.artifacts import ArtifactStore, ArtifactEnvelope

New code should use chuk_artifacts directly:
>>> from chuk_artifacts import ArtifactStore, ArtifactEnvelope

Both approaches work identically and use the same underlying implementation.
"""

from __future__ import annotations
import os
from typing import Any, Dict, Tuple

# Direct imports from chuk_artifacts (hard dependency)
from chuk_artifacts import (
    # Core classes
    ArtifactStore as _ArtifactStore,
    ArtifactEnvelope,
    
    # Exception classes
    ArtifactStoreError,
    ArtifactNotFoundError,
    ArtifactExpiredError,
    ArtifactCorruptedError,
    ProviderError,
    SessionError,
    
    # Operation modules
    CoreStorageOperations,
    PresignedURLOperations,
    MetadataOperations,
    BatchOperations,
    AdminOperations,
    
    # Constants
    _DEFAULT_TTL,
    _DEFAULT_PRESIGN_EXPIRES,
    
    # Convenience functions
    create_store as _create_store,
    quick_store as _quick_store,
    configure_logging as _configure_logging,
)


# =============================================================================
# Compatibility Layer - Minimal parameter mapping only
# =============================================================================

class ArtifactStore(_ArtifactStore):
    """
    Backward compatible ArtifactStore with automatic parameter mapping.
    
    Handles legacy parameter names and delegates everything else to chuk_artifacts.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize with legacy parameter mapping."""
        
        # Map legacy parameter names to new configuration
        if 'redis_url' in kwargs:
            redis_url = kwargs.pop('redis_url')
            kwargs['session_provider'] = 'redis'
            os.environ['SESSION_REDIS_URL'] = redis_url
        
        if 'fs_root' in kwargs:
            fs_root = kwargs.pop('fs_root')
            os.environ['ARTIFACT_FS_ROOT'] = fs_root
        
        if 'bucket_name' in kwargs:
            kwargs['bucket'] = kwargs.pop('bucket_name')
        
        super().__init__(*args, **kwargs)


# =============================================================================
# Convenience Functions - Simple wrappers
# =============================================================================

def create_store(**kwargs) -> ArtifactStore:
    """Create an ArtifactStore with compatibility layer."""
    return ArtifactStore(**kwargs)


async def quick_store(
    data: bytes, 
    *,
    mime: str = "application/octet-stream",
    summary: str = "Quick upload",
    **store_kwargs
) -> Tuple[ArtifactStore, str]:
    """Quick one-off artifact storage with compatibility layer."""
    store = ArtifactStore(**store_kwargs)
    artifact_id = await store.store(data, mime=mime, summary=summary)
    return store, artifact_id


def configure_logging(level: str = "INFO"):
    """Configure logging for both chuk_artifacts and legacy namespaces."""
    import logging
    
    # Configure chuk_artifacts logging
    _configure_logging(level)
    
    # Also configure legacy logging namespace
    logger = logging.getLogger("chuk_mcp_runtime.artifacts")
    logger.setLevel(getattr(logging, level.upper()))


# =============================================================================
# Auto-load .env files
# =============================================================================

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# =============================================================================
# Package exports
# =============================================================================

__version__ = "1.0.0"

__all__ = [
    # Main classes
    "ArtifactStore",
    "ArtifactEnvelope",
    
    # Exceptions
    "ArtifactStoreError", 
    "ArtifactNotFoundError",
    "ArtifactExpiredError",
    "ArtifactCorruptedError",
    "ProviderError",
    "SessionError",
    
    # Operation modules
    "CoreStorageOperations",
    "PresignedURLOperations", 
    "MetadataOperations",
    "BatchOperations",
    "AdminOperations",
    
    # Constants
    "_DEFAULT_TTL",
    "_DEFAULT_PRESIGN_EXPIRES",
    
    # Convenience functions
    "create_store",
    "quick_store",
    "configure_logging",
]