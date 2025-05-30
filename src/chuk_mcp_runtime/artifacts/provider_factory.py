# -*- coding: utf-8 -*-
# chuk_mcp_runtime/artifacts/provider_factory.py
"""
Resolve the storage back-end requested via **ARTIFACT_PROVIDER**.

Built-in providers
──────────────────
• **memory** (default) - in-process, non-persistent store (unit tests, demos)
• **fs**, **filesystem** - local filesystem rooted at `$ARTIFACT_FS_ROOT`
• **s3** - plain AWS or any S3-compatible endpoint
• **ibm_cos** - IBM COS, HMAC credentials (Signature V2)
• **ibm_cos_iam** - IBM COS, IAM API-key / OAuth signature

Any other value is resolved dynamically as
`chuk_mcp_runtime.artifacts.providers.<name>.factory()`.
"""

from __future__ import annotations

import os, aioboto3
from importlib import import_module
from typing import Callable, AsyncContextManager

__all__ = ["factory_for_env"]

# ──────────────────────────────────────────────────────────────────
# Internal helper – generic AWS/S3-compatible factory
# ──────────────────────────────────────────────────────────────────

def _aws_factory() -> Callable[[], AsyncContextManager]:
    """Return a factory producing an *async-context* aioboto3 S3 client."""

    def _make():
        session = aioboto3.Session()
        return session.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT_URL"),
            region_name=os.getenv("AWS_REGION", "us-south"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )

    return _make


# ──────────────────────────────────────────────────────────────────
# Public factory selector
# ──────────────────────────────────────────────────────────────────

def factory_for_env() -> Callable[[], AsyncContextManager]:
    """Return a provider-specific factory based on `$ARTIFACT_PROVIDER`."""

    provider = os.getenv("ARTIFACT_PROVIDER", "memory").lower()

    # Fast paths for the built-ins ------------------------------------------------
    # Memory first as it's the default
    if provider in ("memory", "mem", "inmemory"):
        from .providers import memory
        return memory.factory()

    if provider in ("fs", "filesystem"):
        from .providers import filesystem
        return filesystem.factory()

    if provider == "s3":
        return _aws_factory()

    if provider == "ibm_cos":
        from .providers import ibm_cos
        return ibm_cos.factory()  # returns the zero-arg factory callable

    if provider == "ibm_cos_iam":
        from .providers import ibm_cos_iam
        return ibm_cos_iam.factory  # note: function itself is already the factory

    # ---------------------------------------------------------------------------
    # Fallback: dynamic lookup – allows user-supplied provider implementations.
    # ---------------------------------------------------------------------------
    mod = import_module(f"chuk_mcp_runtime.artifacts.providers.{provider}")
    if not hasattr(mod, "factory"):
        raise AttributeError(
            f"Provider '{provider}' lacks a factory() function"
        )
    # For dynamic providers, call factory() to get the actual factory function
    factory_func = mod.factory
    if callable(factory_func):
        # If it's a function that returns a factory, call it
        try:
            return factory_func()
        except TypeError:
            # If it's already the factory function, return it directly
            return factory_func
    return factory_func