# -*- coding: utf-8 -*-
# chuk_mcp_runtime/artifacts/__init__.py
"""
Asynchronous, object-store-backed artifact manager.

This package provides a high-level interface for storing and retrieving
artifacts across multiple storage backends (S3, IBM COS, filesystem, memory)
with metadata caching and presigned URL support.

Basic Usage
-----------
>>> from chuk_mcp_runtime.artifacts import ArtifactStore
>>> 
>>> # Initialize with default memory providers
>>> store = ArtifactStore()
>>> 
>>> # Or use cloud storage
>>> store = ArtifactStore(
...     storage_provider="ibm_cos",
...     bucket="my-artifacts",
...     session_provider="redis"
... )
>>> 
>>> # Store an artifact
>>> artifact_id = await store.store(
...     data=b"Hello, world!",
...     mime="text/plain",
...     summary="Test document",
...     session_id="user123"
... )
>>> 
>>> # Generate presigned URLs
>>> download_url = await store.presign(artifact_id)
>>> upload_url, new_id = await store.presign_upload(session_id="user123")
>>> 
>>> # Retrieve and manage
>>> data = await store.retrieve(artifact_id)
>>> metadata = await store.metadata(artifact_id)
>>> exists = await store.exists(artifact_id)
>>> deleted = await store.delete(artifact_id)

Supported Providers
------------------
Storage Providers:
    - memory: In-memory storage (default, non-persistent)
    - filesystem: Local filesystem storage
    - s3: Amazon S3
    - ibm_cos: IBM Cloud Object Storage
    - ibm_cos_iam: IBM Cloud Object Storage with IAM

Session Providers:
    - memory: In-memory metadata cache (default)
    - redis: Redis-based metadata cache

Environment Variables
--------------------
ARTIFACT_PROVIDER: Storage provider name (default: memory)
ARTIFACT_BUCKET: Storage bucket/container name (default: mcp-bucket)
SESSION_PROVIDER: Session provider name (default: memory)

For provider-specific configuration:
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY: AWS/S3 credentials
- IBM_COS_ENDPOINT: IBM COS endpoint URL
- IBM_COS_APIKEY, IBM_COS_INSTANCE_CRN: IBM COS IAM credentials
- SESSION_REDIS_URL: Redis connection URL
- ARTIFACT_FS_ROOT: Filesystem storage root directory

Examples
--------
Memory Storage (Development):
>>> store = ArtifactStore()  # Uses memory for everything

Cloud Storage with Redis Cache:
>>> store = ArtifactStore(
...     storage_provider="ibm_cos",
...     bucket="production-artifacts",
...     session_provider="redis"
... )

Local Filesystem:
>>> store = ArtifactStore(
...     storage_provider="filesystem",
...     bucket="local-artifacts"
... )

Presigned Upload Workflow:
>>> # Generate upload URL for user
>>> upload_url, artifact_id = await store.presign_upload_and_register(
...     mime="image/jpeg",
...     summary="User profile photo",
...     session_id="user456"
... )
>>> # User uploads directly to upload_url
>>> # File is immediately available via artifact_id
>>> download_url = await store.presign(artifact_id)
"""

from __future__ import annotations

# Core classes
from .store import ArtifactStore

# Exception classes
from .exceptions import (
    ArtifactStoreError,
    ArtifactNotFoundError,
    ArtifactExpiredError,
    ArtifactCorruptedError,
    ProviderError,
    SessionError,
)

# Operation modules (for advanced usage)
from .core import CoreStorageOperations
from .presigned import PresignedURLOperations
from .metadata import MetadataOperations
from .batch import BatchOperations
from .admin import AdminOperations

# Constants
from .store import _DEFAULT_TTL, _DEFAULT_PRESIGN_EXPIRES

__version__ = "1.0.0"

__all__ = [
    # Main class
    "ArtifactStore",
    
    # Exceptions
    "ArtifactStoreError", 
    "ArtifactNotFoundError",
    "ArtifactExpiredError",
    "ArtifactCorruptedError",
    "ProviderError",
    "SessionError",
    
    # Operation modules (advanced usage)
    "CoreStorageOperations",
    "PresignedURLOperations", 
    "MetadataOperations",
    "BatchOperations",
    "AdminOperations",
    
    # Constants
    "_DEFAULT_TTL",
    "_DEFAULT_PRESIGN_EXPIRES",
]

# Convenience aliases for common operations
def create_store(**kwargs) -> ArtifactStore:
    """
    Convenience function to create an ArtifactStore with sensible defaults.
    
    Parameters
    ----------
    **kwargs
        Passed to ArtifactStore constructor
        
    Returns
    -------
    ArtifactStore
        Configured artifact store
        
    Examples
    --------
    >>> store = create_store()  # Memory-based
    >>> store = create_store(storage_provider="ibm_cos", bucket="my-bucket")
    """
    return ArtifactStore(**kwargs)


async def quick_store(
    data: bytes, 
    *,
    mime: str = "application/octet-stream",
    summary: str = "Quick upload",
    **store_kwargs
) -> tuple[ArtifactStore, str]:
    """
    Convenience function for quick one-off artifact storage.
    
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
        (store_instance, artifact_id)
        
    Examples
    --------
    >>> store, artifact_id = await quick_store(
    ...     b"Hello world", 
    ...     mime="text/plain",
    ...     storage_provider="filesystem"
    ... )
    >>> url = await store.presign(artifact_id)
    """
    store = ArtifactStore(**store_kwargs)
    artifact_id = await store.store(data, mime=mime, summary=summary)
    return store, artifact_id


# Module-level configuration helper
def configure_logging(level: str = "INFO"):
    """
    Configure logging for the artifacts package.
    
    Parameters
    ----------
    level : str
        Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    import logging
    
    logger = logging.getLogger("chuk_mcp_runtime.artifacts")
    logger.setLevel(getattr(logging, level.upper()))
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)


# Auto-load .env files if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, continue without it