# -*- coding: utf-8 -*-
# chuk_mcp_runtime/artifacts/store.py
"""
Asynchronous, object-store-backed artefact manager (aioboto3 ≥ 12).

Highlights
──────────
• Pure-async: every S3 call is wrapped in `async with s3_factory() as s3`.
• Back-end agnostic: set ARTIFACT_PROVIDER=s3 / ibm_cos / … or inject a factory.
• Metadata cached in Redis, keyed **only** by `artifact_id`.
• Presigned URLs on demand, configurable TTL for both data & metadata.
• Enhanced error handling, logging, and operational features.
"""

from __future__ import annotations

import os, uuid, json, hashlib, ssl, time, logging
from datetime import datetime
from types import ModuleType
from typing import Any, Dict, List, Callable, AsyncContextManager, Optional, Union

try:
    import aioboto3
    import redis.asyncio as aioredis
except ImportError as e:
    raise ImportError(f"Required dependencies missing: {e}. Install with: pip install aioboto3 redis") from e

# Configure structured logging
logger = logging.getLogger(__name__)

_ANON_PREFIX = "anon"
_DEFAULT_TTL = 900  # seconds (15 minutes for metadata)
_DEFAULT_PRESIGN_EXPIRES = 3600  # seconds (1 hour for presigned URLs)

# ─────────────────────────────────────────────────────────────────────
# Default factory (AWS env or any generic S3 endpoint)
# ─────────────────────────────────────────────────────────────────────
def _default_factory() -> Callable[[], AsyncContextManager]:
    """Return a zero-arg callable that yields an async ctx-mgr S3 client."""
    from .provider_factory import factory_for_env
    return factory_for_env()


# ─────────────────────────────────────────────────────────────────────
class ArtifactStoreError(Exception):
    """Base exception for artifact store operations."""
    pass


class ArtifactNotFoundError(ArtifactStoreError):
    """Raised when an artifact cannot be found."""
    pass


class ArtifactExpiredError(ArtifactStoreError):
    """Raised when an artifact has expired."""
    pass


class ArtifactCorruptedError(ArtifactStoreError):
    """Raised when artifact metadata is corrupted."""
    pass


class ProviderError(ArtifactStoreError):
    """Raised when the storage provider encounters an error."""
    pass


# ─────────────────────────────────────────────────────────────────────
class ArtifactStore:
    """
    Asynchronous artifact storage with Redis metadata caching.
    
    Parameters
    ----------
    bucket : str
        Storage bucket/container name
    redis_url : str   
        Redis connection URL (redis:// or rediss://)
    s3_factory : Callable[[], AsyncContextManager], optional
        Custom S3 client factory
    provider : str, optional   
        Provider name (looked up under artifacts.providers.<name>.factory)
    max_retries : int, optional
        Maximum retry attempts for storage operations (default: 3)
    """

    def __init__(
        self,
        *,
        bucket: str,
        redis_url: str,
        s3_factory: Optional[Callable[[], AsyncContextManager]] = None,
        provider: Optional[str] = None,
        max_retries: int = 3,
    ):
        if s3_factory and provider:
            raise ValueError("Specify either s3_factory or provider—not both")

        if s3_factory:
            self._s3_factory = s3_factory
        elif provider:
            self._s3_factory = self._load_provider(provider)
        else:
            self._s3_factory = _default_factory()

        self.bucket = bucket
        self.max_retries = max_retries
        self._provider_name = provider or "default"
        self._closed = False

        # Configure Redis connection
        tls_insecure = os.getenv("REDIS_TLS_INSECURE", "0") == "1"
        redis_kwargs = {"ssl_cert_reqs": ssl.CERT_NONE} if tls_insecure else {}
        self._redis = aioredis.from_url(redis_url, decode_responses=True, **redis_kwargs)

        logger.info(
            "ArtifactStore initialized",
            extra={
                "bucket": bucket,
                "provider": self._provider_name,
                "redis_url": redis_url.split("@")[-1] if "@" in redis_url else redis_url,  # Hide credentials
            }
        )

    # ─────────────────────────────────────────────────────────────────
    # Core storage operations
    # ─────────────────────────────────────────────────────────────────

    async def store(
        self,
        data: bytes,
        *,
        mime: str,
        summary: str,
        meta: Dict[str, Any] | None = None,
        filename: str | None = None,
        session_id: str | None = None,
        ttl: int = _DEFAULT_TTL,
    ) -> str:
        """
        Store artifact data with metadata.
        
        Parameters
        ----------
        data : bytes
            The artifact data to store
        mime : str
            MIME type of the artifact
        summary : str
            Human-readable description
        meta : dict, optional
            Additional metadata
        filename : str, optional
            Original filename
        session_id : str, optional
            Session identifier for organization
        ttl : int, optional
            Metadata TTL in seconds
            
        Returns
        -------
        str
            Unique artifact identifier
            
        Raises
        ------
        ProviderError
            If storage operation fails
        ArtifactStoreError
            If metadata caching fails
        """
        if self._closed:
            raise ArtifactStoreError("Store has been closed")
            
        start_time = time.time()
        artifact_id = uuid.uuid4().hex
        
        # ✅ FIX: Use underscore instead of colon for IBM COS presigned URL compatibility
        scope = session_id or f"{_ANON_PREFIX}_{artifact_id}"
        key = f"sess/{scope}/{artifact_id}"

        try:
            # Store in object storage with retries
            await self._store_with_retry(data, key, mime, filename, scope)

            # Build metadata record
            record = {
                "scope": scope,
                "key": key,
                "mime": mime,
                "summary": summary,
                "meta": meta or {},
                "filename": filename,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "stored_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "ttl": ttl,
                "provider": self._provider_name,
            }

            # Cache metadata in Redis
            await self._redis.setex(artifact_id, ttl, json.dumps(record))

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "Artifact stored successfully",
                extra={
                    "artifact_id": artifact_id,
                    "bytes": len(data),
                    "mime": mime,
                    "duration_ms": duration_ms,
                    "provider": self._provider_name,
                }
            )

            return artifact_id

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Artifact storage failed",
                extra={
                    "artifact_id": artifact_id,
                    "error": str(e),
                    "duration_ms": duration_ms,
                    "provider": self._provider_name,
                },
                exc_info=True
            )
            
            if "redis" in str(e).lower():
                raise ArtifactStoreError(f"Metadata caching failed: {e}") from e
            else:
                raise ProviderError(f"Storage operation failed: {e}") from e

    async def _store_with_retry(self, data: bytes, key: str, mime: str, filename: str, scope: str):
        """Store data with retry logic."""
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                async with self._s3_factory() as s3:
                    await s3.put_object(
                        Bucket=self.bucket,
                        Key=key,
                        Body=data,
                        ContentType=mime,
                        Metadata={"filename": filename or "", "scope": scope},
                    )
                return  # Success
                
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(
                        f"Storage attempt {attempt + 1} failed, retrying in {wait_time}s",
                        extra={"error": str(e), "attempt": attempt + 1}
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"All {self.max_retries} storage attempts failed")
        
        raise last_exception

    async def retrieve(self, artifact_id: str) -> bytes:
        """
        Retrieve artifact data directly.
        
        Parameters
        ----------
        artifact_id : str
            The artifact identifier
            
        Returns
        -------
        bytes
            The artifact data
            
        Raises
        ------
        ArtifactNotFoundError
            If artifact doesn't exist or has expired
        ProviderError
            If retrieval fails
        """
        if self._closed:
            raise ArtifactStoreError("Store has been closed")
            
        start_time = time.time()
        
        try:
            record = await self._get_record(artifact_id)
            
            async with self._s3_factory() as s3:
                response = await s3.get_object(Bucket=self.bucket, Key=record["key"])
                data = response["Body"]
                
                # Verify integrity if SHA256 is available
                if "sha256" in record:
                    computed_hash = hashlib.sha256(data).hexdigest()
                    if computed_hash != record["sha256"]:
                        raise ArtifactCorruptedError(
                            f"SHA256 mismatch: expected {record['sha256']}, got {computed_hash}"
                        )
                
                duration_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "Artifact retrieved successfully",
                    extra={
                        "artifact_id": artifact_id,
                        "bytes": len(data),
                        "duration_ms": duration_ms,
                    }
                )
                
                return data
                
        except (ArtifactNotFoundError, ArtifactExpiredError, ArtifactCorruptedError):
            raise
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Artifact retrieval failed",
                extra={
                    "artifact_id": artifact_id,
                    "error": str(e),
                    "duration_ms": duration_ms,
                }
            )
            raise ProviderError(f"Retrieval failed: {e}") from e

    # ─────────────────────────────────────────────────────────────────
    # Presigned URL operations
    # ─────────────────────────────────────────────────────────────────

    async def presign(self, artifact_id: str, expires: int = _DEFAULT_PRESIGN_EXPIRES) -> str:
        """
        Generate a presigned URL for artifact download.
        
        Parameters
        ----------
        artifact_id : str
            The artifact identifier
        expires : int, optional
            URL expiration time in seconds (default: 1 hour)
            
        Returns
        -------
        str
            Presigned URL for downloading the artifact
            
        Raises
        ------
        ArtifactNotFoundError
            If artifact doesn't exist or has expired
        NotImplementedError
            If provider doesn't support presigned URLs
        """
        if self._closed:
            raise ArtifactStoreError("Store has been closed")
            
        start_time = time.time()
        
        try:
            record = await self._get_record(artifact_id)
            
            async with self._s3_factory() as s3:
                url = await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": record["key"]},
                    ExpiresIn=expires,
                )
                
                duration_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "Presigned URL generated",
                    extra={
                        "artifact_id": artifact_id,
                        "expires_in": expires,
                        "duration_ms": duration_ms,
                    }
                )
                
                return url
                
        except (ArtifactNotFoundError, ArtifactExpiredError):
            raise
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Presigned URL generation failed",
                extra={
                    "artifact_id": artifact_id,
                    "error": str(e),
                    "duration_ms": duration_ms,
                }
            )
            
            if "oauth" in str(e).lower() or "credential" in str(e).lower():
                raise NotImplementedError(
                    "This provider cannot generate presigned URLs with the "
                    "current credential type (e.g. OAuth). Use HMAC creds instead."
                ) from e
            else:
                raise ProviderError(f"Presigned URL generation failed: {e}") from e

    async def presign_short(self, artifact_id: str) -> str:
        """Generate a short-lived presigned URL (15 minutes)."""
        return await self.presign(artifact_id, expires=900)
    
    async def presign_medium(self, artifact_id: str) -> str:
        """Generate a medium-lived presigned URL (1 hour)."""
        return await self.presign(artifact_id, expires=3600)
    
    async def presign_long(self, artifact_id: str) -> str:
        """Generate a long-lived presigned URL (24 hours)."""
        return await self.presign(artifact_id, expires=86400)

    # ─────────────────────────────────────────────────────────────────
    # Metadata and utility operations
    # ─────────────────────────────────────────────────────────────────

    async def metadata(self, artifact_id: str) -> Dict[str, Any]:
        """
        Get artifact metadata.
        
        Parameters
        ----------
        artifact_id : str
            The artifact identifier
            
        Returns
        -------
        dict
            Artifact metadata
            
        Raises
        ------
        ArtifactNotFoundError
            If artifact doesn't exist or has expired
        """
        return await self._get_record(artifact_id)

    async def exists(self, artifact_id: str) -> bool:
        """
        Check if artifact exists and hasn't expired.
        
        Parameters
        ----------
        artifact_id : str
            The artifact identifier
            
        Returns
        -------
        bool
            True if artifact exists, False otherwise
        """
        try:
            await self._get_record(artifact_id)
            return True
        except (ArtifactNotFoundError, ArtifactExpiredError):
            return False

    async def delete(self, artifact_id: str) -> bool:
        """
        Delete artifact and its metadata.
        
        Parameters
        ----------
        artifact_id : str
            The artifact identifier
            
        Returns
        -------
        bool
            True if deleted, False if not found
        """
        if self._closed:
            raise ArtifactStoreError("Store has been closed")
            
        try:
            record = await self._get_record(artifact_id)
            
            # Delete from object storage
            async with self._s3_factory() as s3:
                await s3.delete_object(Bucket=self.bucket, Key=record["key"])
            
            # Delete metadata from Redis
            await self._redis.delete(artifact_id)
            
            logger.info("Artifact deleted", extra={"artifact_id": artifact_id})
            return True
            
        except (ArtifactNotFoundError, ArtifactExpiredError):
            logger.warning("Attempted to delete non-existent artifact", extra={"artifact_id": artifact_id})
            return False
        except Exception as e:
            logger.error(
                "Artifact deletion failed",
                extra={"artifact_id": artifact_id, "error": str(e)}
            )
            raise ProviderError(f"Deletion failed: {e}") from e

    async def list_by_session(self, session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List artifacts for a session (requires Redis SCAN).
        
        Parameters
        ----------
        session_id : str
            Session identifier
        limit : int, optional
            Maximum number of artifacts to return
            
        Returns
        -------
        list
            List of artifact metadata records
        """
        artifacts = []
        cursor = 0
        count = 0
        
        while count < limit:
            cursor, keys = await self._redis.scan(cursor=cursor, match="*", count=50)
            
            for key in keys:
                try:
                    record = await self._get_record(key)
                    if record.get("scope") == session_id:
                        artifacts.append({**record, "artifact_id": key})
                        count += 1
                        if count >= limit:
                            break
                except (ArtifactNotFoundError, ArtifactExpiredError):
                    continue
                    
            if cursor == 0:  # Full scan complete
                break
                
        return artifacts

    # ─────────────────────────────────────────────────────────────────
    # Batch operations
    # ─────────────────────────────────────────────────────────────────

    async def store_batch(
        self,
        items: List[Dict[str, Any]],
        session_id: str | None = None,
        ttl: int = _DEFAULT_TTL,
    ) -> List[str]:
        """
        Store multiple artifacts in a batch operation.
        
        Parameters
        ----------
        items : list
            List of dicts with keys: data, mime, summary, meta, filename
        session_id : str, optional
            Session identifier for all artifacts
        ttl : int, optional
            Metadata TTL for all artifacts
            
        Returns
        -------
        list
            List of artifact IDs
        """
        if self._closed:
            raise ArtifactStoreError("Store has been closed")
            
        artifact_ids = []
        failed_items = []
        
        # Use Redis pipeline for metadata
        pipe = self._redis.pipeline()
        
        for i, item in enumerate(items):
            try:
                artifact_id = uuid.uuid4().hex
                scope = session_id or f"{_ANON_PREFIX}_{artifact_id}"
                key = f"sess/{scope}/{artifact_id}"
                
                # Store in object storage
                await self._store_with_retry(
                    item["data"], key, item["mime"], 
                    item.get("filename"), scope
                )
                
                # Prepare metadata for pipeline
                record = {
                    "scope": scope,
                    "key": key,
                    "mime": item["mime"],
                    "summary": item["summary"],
                    "meta": item.get("meta", {}),
                    "filename": item.get("filename"),
                    "bytes": len(item["data"]),
                    "sha256": hashlib.sha256(item["data"]).hexdigest(),
                    "stored_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "ttl": ttl,
                    "provider": self._provider_name,
                }
                
                pipe.setex(artifact_id, ttl, json.dumps(record))
                artifact_ids.append(artifact_id)
                
            except Exception as e:
                logger.error(f"Batch item {i} failed: {e}")
                failed_items.append(i)
                artifact_ids.append(None)  # Placeholder
        
        # Execute Redis pipeline
        await pipe.execute()
        
        if failed_items:
            logger.warning(f"Batch operation completed with {len(failed_items)} failures")
        
        return artifact_ids

    # ─────────────────────────────────────────────────────────────────
    # Administrative and debugging
    # ─────────────────────────────────────────────────────────────────

    async def validate_configuration(self) -> Dict[str, Any]:
        """
        Validate store configuration and connectivity.
        
        Returns
        -------
        dict
            Validation results for Redis and storage provider
        """
        results = {"timestamp": datetime.utcnow().isoformat() + "Z"}
        
        # Test Redis connection
        try:
            await self._redis.ping()
            results["redis"] = {"status": "ok", "url": str(self._redis.connection_pool.connection_kwargs.get("host", "unknown"))}
        except Exception as e:
            results["redis"] = {"status": "error", "message": str(e)}
        
        # Test storage provider
        try:
            async with self._s3_factory() as s3:
                await s3.head_bucket(Bucket=self.bucket)
            results["storage"] = {"status": "ok", "bucket": self.bucket, "provider": self._provider_name}
        except Exception as e:
            results["storage"] = {"status": "error", "message": str(e), "provider": self._provider_name}
        
        return results

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.
        
        Returns
        -------
        dict
            Statistics about stored artifacts
        """
        # This is expensive for large stores - consider Redis counters in production
        info = await self._redis.info()
        
        return {
            "redis_keys": info.get("db0", {}).get("keys", 0) if "db0" in info else 0,
            "redis_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
            "provider": self._provider_name,
            "bucket": self.bucket,
        }

    # ─────────────────────────────────────────────────────────────────
    # Resource management
    # ─────────────────────────────────────────────────────────────────

    async def close(self):
        """Clean up Redis connections and mark store as closed."""
        if not self._closed:
            await self._redis.close()
            self._closed = True
            logger.info("ArtifactStore closed")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ─────────────────────────────────────────────────────────────────
    # Helper functions
    # ─────────────────────────────────────────────────────────────────

    def _load_provider(self, name: str) -> Callable[[], AsyncContextManager]:
        """Load storage provider by name."""
        from importlib import import_module

        try:
            mod: ModuleType = import_module(f"chuk_mcp_runtime.artifacts.providers.{name}")
        except ModuleNotFoundError as exc:
            raise ValueError(f"Unknown provider '{name}'") from exc

        if not hasattr(mod, "factory"):
            raise AttributeError(f"Provider '{name}' lacks factory()")
        
        logger.info(f"Loaded provider: {name}")
        return mod.factory  # type: ignore[return-value]

    async def _get_record(self, artifact_id: str) -> Dict[str, Any]:
        """
        Retrieve artifact metadata from Redis with enhanced error handling.
        
        Parameters
        ----------
        artifact_id : str
            The artifact identifier
            
        Returns
        -------
        dict
            Artifact metadata record
            
        Raises
        ------
        ArtifactNotFoundError
            If artifact doesn't exist
        ArtifactExpiredError  
            If artifact has expired
        ArtifactCorruptedError
            If metadata is corrupted
        """
        try:
            raw = await self._redis.get(artifact_id)
        except Exception as e:
            raise ArtifactStoreError(f"Redis error retrieving {artifact_id}: {e}") from e
        
        if raw is None:
            # Could be expired or never existed - we can't distinguish without additional metadata
            raise ArtifactNotFoundError(f"Artifact {artifact_id} not found or expired")
        
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Corrupted metadata for artifact {artifact_id}: {e}")
            # Clean up corrupted entry
            await self._redis.delete(artifact_id)
            raise ArtifactCorruptedError(f"Corrupted metadata for artifact {artifact_id}") from e