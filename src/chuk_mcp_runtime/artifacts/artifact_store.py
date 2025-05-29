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
"""

from __future__ import annotations

import os, uuid, json, hashlib, ssl, aioboto3, redis.asyncio as aioredis
from datetime import datetime
from types import ModuleType
from typing import Any, Dict, Callable, AsyncContextManager, Optional

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
class ArtifactStore:
    """
    Parameters
    ----------
    bucket      : str
    redis_url   : str   redis:// or rediss://
    s3_factory  : Callable[[], AsyncContextManager] | None
    provider    : str | None   (looked up under artifacts.providers.<n>.factory)
    """

    def __init__(
        self,
        *,
        bucket: str,
        redis_url: str,
        s3_factory: Optional[Callable[[], AsyncContextManager]] = None,
        provider: Optional[str] = None,
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

        tls_insecure = os.getenv("REDIS_TLS_INSECURE", "0") == "1"
        redis_kwargs = {"ssl_cert_reqs": ssl.CERT_NONE} if tls_insecure else {}
        self._redis = aioredis.from_url(redis_url, decode_responses=True, **redis_kwargs)

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
        artifact_id = uuid.uuid4().hex
        # ✅ FIX: Use underscore instead of colon for IBM COS presigned URL compatibility
        scope = session_id or f"{_ANON_PREFIX}_{artifact_id}"
        key = f"sess/{scope}/{artifact_id}"

        async with self._s3_factory() as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=mime,
                Metadata={"filename": filename or "", "scope": scope},
            )

        record = {
            "scope":      scope,
            "key":        key,
            "mime":       mime,
            "summary":    summary,
            "meta":       meta or {},
            "filename":   filename,
            "bytes":      len(data),
            "sha256":     hashlib.sha256(data).hexdigest(),
            "stored_at":  datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "ttl":        ttl,
        }
        await self._redis.setex(artifact_id, ttl, json.dumps(record))
        return artifact_id

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
        """
        rec = await self._get_record(artifact_id)
        async with self._s3_factory() as s3:
            try:
                return await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": rec["key"]},
                    ExpiresIn=expires,
                )
            except Exception as e:
                raise NotImplementedError(
                    "This provider cannot generate presigned URLs with the "
                    "current credential type (e.g. OAuth). Use HMAC creds instead."
                ) from e

    async def metadata(self, artifact_id: str) -> Dict[str, Any]:
        return await self._get_record(artifact_id)

    # ─────────────────────────────────────────────────────────────────
    # Convenience methods for different expiry periods
    # ─────────────────────────────────────────────────────────────────
    
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
    # Helper functions
    # ─────────────────────────────────────────────────────────────────
    def _load_provider(self, name: str) -> Callable[[], AsyncContextManager]:
        from importlib import import_module

        try:
            mod: ModuleType = import_module(
                f"chuk_mcp_runtime.artifacts.providers.{name}"
            )
        except ModuleNotFoundError as exc:
            raise ValueError(f"Unknown provider '{name}'") from exc

        if not hasattr(mod, "factory"):
            raise AttributeError(f"Provider '{name}' lacks factory()")
        return mod.factory  # type: ignore[return-value]

    async def _get_record(self, artifact_id: str) -> Dict[str, Any]:
        raw = await self._redis.get(artifact_id)
        if raw is None:
            raise FileNotFoundError("Artefact expired or not found")
        return json.loads(raw)