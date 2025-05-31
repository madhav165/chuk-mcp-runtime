# -*- coding: utf-8 -*-
# chuk_mcp_runtime/artifacts/__init__.py
"""
Backward compatibility layer for chuk_artifacts.

This module provides a compatibility layer that exposes chuk_artifacts
functionality while maintaining the existing chuk_mcp_runtime.artifacts API.

Migration Path
--------------
Old code using chuk_mcp_runtime.artifacts will continue to work:
>>> from chuk_mcp_runtime.artifacts import ArtifactStore
>>> store = ArtifactStore()

New code should use chuk_artifacts directly:
>>> from chuk_artifacts import ArtifactStore  
>>> store = ArtifactStore()

Both approaches work identically and use the same underlying implementation.
"""

from __future__ import annotations
import warnings
from typing import Any, Dict, List, Optional, Tuple

# Import everything from the new chuk_artifacts package
try:
    from chuk_artifacts import (
        # Core classes
        ArtifactStore as _ArtifactStore,
        
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
    
    _CHUK_ARTIFACTS_AVAILABLE = True
    
except ImportError:
    # Fallback to legacy implementation if chuk_artifacts not available
    _CHUK_ARTIFACTS_AVAILABLE = False
    warnings.warn(
        "chuk_artifacts package not found. Please install it for the latest features: "
        "pip install chuk-artifacts",
        ImportWarning,
        stacklevel=2
    )
    
    # You would import your legacy classes here
    # from .legacy_store import ArtifactStore as _ArtifactStore
    # For now, we'll create a placeholder
    class _ArtifactStore:
        def __init__(self, *args, **kwargs):
            raise ImportError("chuk_artifacts package required")


# =============================================================================
# Compatibility Layer - Maintains existing API
# =============================================================================

class ArtifactStore(_ArtifactStore):
    """
    Backward compatible ArtifactStore that wraps chuk_artifacts.ArtifactStore.
    
    This class maintains the existing chuk_mcp_runtime.artifacts API while
    delegating to the new modular chuk_artifacts implementation.
    
    All existing code continues to work unchanged, while new features from
    chuk_artifacts are automatically available.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize with backward compatibility support."""
        if not _CHUK_ARTIFACTS_AVAILABLE:
            raise ImportError(
                "chuk_artifacts package is required. Install with: pip install chuk-artifacts"
            )
        
        # Handle any legacy parameter mappings if needed
        # For example, if you had different parameter names in the old API:
        # if 'redis_url' in kwargs:
        #     kwargs['session_provider'] = 'redis'
        #     os.environ['SESSION_REDIS_URL'] = kwargs.pop('redis_url')
        
        super().__init__(*args, **kwargs)
    
    # You can add any legacy methods that don't exist in the new implementation
    # or modify behavior for backward compatibility
    
    async def legacy_method_example(self, *args, **kwargs):
        """Example of a legacy method that maps to new functionality."""
        warnings.warn(
            "legacy_method_example is deprecated. Use the new API instead.",
            DeprecationWarning,
            stacklevel=2
        )
        # Map to new method
        return await self.store(*args, **kwargs)


# =============================================================================
# Convenience Functions - Enhanced versions
# =============================================================================

def create_store(**kwargs) -> ArtifactStore:
    """
    Create an ArtifactStore with sensible defaults.
    
    This is a compatibility wrapper around chuk_artifacts.create_store
    that returns a chuk_mcp_runtime.artifacts.ArtifactStore instance.
    
    Parameters
    ----------
    **kwargs
        Passed to ArtifactStore constructor
        
    Returns
    -------
    ArtifactStore
        Configured artifact store with compatibility layer
        
    Examples
    --------
    >>> store = create_store()  # Memory-based
    >>> store = create_store(storage_provider="ibm_cos", bucket="my-bucket")
    """
    if not _CHUK_ARTIFACTS_AVAILABLE:
        raise ImportError("chuk_artifacts package required")
    return ArtifactStore(**kwargs)


async def quick_store(
    data: bytes, 
    *,
    mime: str = "application/octet-stream",
    summary: str = "Quick upload",
    **store_kwargs
) -> Tuple[ArtifactStore, str]:
    """
    Quick one-off artifact storage with compatibility layer.
    
    Parameters
    ----------
    data : bytes
        Data to store
    mime : str, optional
        MIME type
    summary : str, optional
        Description
    **store_kwargs
        Passed to ArtifactStore constructor
        
    Returns
    -------
    tuple
        (store_instance, artifact_id) where store_instance includes compatibility layer
        
    Examples
    --------
    >>> store, artifact_id = await quick_store(
    ...     b"Hello world", 
    ...     mime="text/plain",
    ...     storage_provider="filesystem"
    ... )
    >>> url = await store.presign(artifact_id)
    """
    if not _CHUK_ARTIFACTS_AVAILABLE:
        raise ImportError("chuk_artifacts package required")
    
    store = ArtifactStore(**store_kwargs)
    artifact_id = await store.store(data, mime=mime, summary=summary)
    return store, artifact_id


def configure_logging(level: str = "INFO"):
    """
    Configure logging for the artifacts package.
    
    This configures both chuk_artifacts and chuk_mcp_runtime.artifacts logging.
    
    Parameters
    ----------
    level : str
        Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    import logging
    
    # Configure chuk_artifacts logging
    if _CHUK_ARTIFACTS_AVAILABLE:
        _configure_logging(level)
    
    # Also configure legacy logging
    logger = logging.getLogger("chuk_mcp_runtime.artifacts")
    logger.setLevel(getattr(logging, level.upper()))
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)


# =============================================================================
# Migration Helpers
# =============================================================================

def get_migration_guide() -> str:
    """
    Get migration guide for transitioning to chuk_artifacts.
    
    Returns
    -------
    str
        Migration guide text
    """
    return """
Migration Guide: chuk_mcp_runtime.artifacts → chuk_artifacts
===========================================================

Your existing code continues to work unchanged, but you can migrate to
the new package for better performance and features:

BEFORE (still works):
    from chuk_mcp_runtime.artifacts import ArtifactStore
    
AFTER (recommended):
    from chuk_artifacts import ArtifactStore

Benefits of migrating:
- Better performance with the new modular architecture
- Enhanced type safety and IDE support  
- More comprehensive error handling
- Access to latest features and improvements
- Direct dependency management

No code changes required - just update the import statement!
"""


def check_compatibility() -> Dict[str, Any]:
    """
    Check compatibility status and available features.
    
    Returns
    -------
    dict
        Compatibility status information
    """
    return {
        "chuk_artifacts_available": _CHUK_ARTIFACTS_AVAILABLE,
        "compatibility_layer": True,
        "legacy_support": True,
        "migration_required": False,
        "recommended_action": "Consider migrating imports to chuk_artifacts for latest features",
        "version": __version__ if _CHUK_ARTIFACTS_AVAILABLE else "legacy"
    }


# =============================================================================
# Auto-load .env files if available
# =============================================================================

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, continue without it


# =============================================================================
# Package Metadata
# =============================================================================

__version__ = "1.0.0"

__all__ = [
    # Main class (with compatibility layer)
    "ArtifactStore",
    
    # Exceptions (re-exported from chuk_artifacts)
    "ArtifactStoreError", 
    "ArtifactNotFoundError",
    "ArtifactExpiredError",
    "ArtifactCorruptedError",
    "ProviderError",
    "SessionError",
    
    # Operation modules (re-exported from chuk_artifacts)
    "CoreStorageOperations",
    "PresignedURLOperations", 
    "MetadataOperations",
    "BatchOperations",
    "AdminOperations",
    
    # Constants (re-exported from chuk_artifacts)
    "_DEFAULT_TTL",
    "_DEFAULT_PRESIGN_EXPIRES",
    
    # Convenience functions (with compatibility layer)
    "create_store",
    "quick_store",
    "configure_logging",
    
    # Migration helpers
    "get_migration_guide",
    "check_compatibility",
]


# =============================================================================
# Module-level compatibility check
# =============================================================================

if not _CHUK_ARTIFACTS_AVAILABLE:
    warnings.warn(
        "chuk_mcp_runtime.artifacts is using legacy implementation. "
        "Install chuk-artifacts for the latest features: pip install chuk-artifacts",
        ImportWarning,
        stacklevel=2
    )


# =============================================================================
# Backward Compatibility Examples
# =============================================================================

"""
Usage Examples (All Backward Compatible)
=========================================

# Existing code continues to work unchanged:
from chuk_mcp_runtime.artifacts import ArtifactStore

store = ArtifactStore(
    storage_provider="ibm_cos",
    bucket="my-artifacts",
    session_provider="redis"
)

artifact_id = await store.store(
    data=b"Hello, world!",
    mime="text/plain",
    summary="Test document",
    session_id="user123"
)

# All existing methods work exactly the same:
download_url = await store.presign(artifact_id)
upload_url, new_id = await store.presign_upload(session_id="user123")
data = await store.retrieve(artifact_id)
metadata = await store.metadata(artifact_id)
exists = await store.exists(artifact_id)
deleted = await store.delete(artifact_id)

# New features are automatically available:
stats = await store.get_stats()
config = await store.validate_configuration()
batch_ids = await store.store_batch(items)

# Migration helpers:
print(get_migration_guide())
print(check_compatibility())
"""