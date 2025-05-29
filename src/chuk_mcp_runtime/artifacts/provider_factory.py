# -*- coding: utf-8 -*-
# chuk_mcp_runtime/artifacts/provider_factory.py
"""
Resolve the storage back-end requested via ARTIFACT_PROVIDER.

• factory_for_env() → zero-arg callable that yields an **async context-manager**
  S3 client.

• s3_client_for_env() → legacy helper that eagerly opens the factory once
  and returns a concrete client (deprecated).
"""

from __future__ import annotations
import os, warnings, aioboto3
from importlib import import_module
from typing import Callable, AsyncContextManager


# ─────────────────────────────────────────────────────────────────────
def _aws_factory() -> Callable[[], AsyncContextManager]:
    """Factory for AWS or any S3-compatible endpoint via env vars."""

    def _make():
        session = aioboto3.Session()
        return session.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT_URL"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )

    return _make


# ─────────────────────────────────────────────────────────────────────
def factory_for_env() -> Callable[[], AsyncContextManager]:
    """
    Return a zero-arg factory for the provider named in ARTIFACT_PROVIDER.

    Built-ins:
      • s3            (default) – generic AWS / MinIO / Wasabi …
      • ibm_cos       – HMAC credentials
      • ibm_cos_iam   – IAM API-key (oauth signature)

    Anything else is resolved as
      chuk_mcp_runtime.artifacts.providers.<name>.factory
    """
    provider = os.getenv("ARTIFACT_PROVIDER", "s3").lower()

    if provider == "s3":
        return _aws_factory()

    if provider == "ibm_cos":
        from .providers import ibm_cos
        return ibm_cos.factory()        # Call it with defaults to get the _make function

    if provider == "ibm_cos_iam":
        from .providers import ibm_cos_iam
        return ibm_cos_iam.factory      # Return the factory function

    # dynamic lookup
    mod = import_module(f"chuk_mcp_runtime.artifacts.providers.{provider}")
    if not hasattr(mod, "factory"):
        raise AttributeError(f"Provider '{provider}' lacks a factory() function")
    return mod.factory                  # ← note: NO parentheses