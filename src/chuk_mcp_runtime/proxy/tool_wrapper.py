"""
chuk_mcp_runtime.proxy.tool_wrapper
===================================

Create local async wrappers for every remote MCP tool.

 • dot wrapper … proxy.<server>.<tool>
 • underscore …  <server>_<tool>   (OpenAI-style)

Wrappers are always inserted into
`chuk_mcp_runtime.common.mcp_tool_decorator.TOOLS_REGISTRY`
via `@mcp_tool` and—if present—also into `ToolRegistryProvider`.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Optional

from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from chuk_mcp_runtime.server.logging_config import get_logger

try:                                      # Optional dependency
    from chuk_tool_processor.registry import ToolRegistryProvider
except ModuleNotFoundError:               # noqa: D401
    ToolRegistryProvider = None  # type: ignore

logger = get_logger("chuk_mcp_runtime.proxy.tool_wrapper")


# ───────────────────────── helpers ──────────────────────────
def _meta_get(meta: Any, key: str, default: Any) -> Any:
    """`meta` can be dict _or_ pydantic model – fetch *key* robustly."""
    return meta.get(key, default) if isinstance(meta, dict) else getattr(meta, key, default)


def _tp_register(
    registry: Any,
    *,
    name: str,
    namespace: str,
    func: Callable[..., Any],
    metadata: Any,
) -> None:
    """
    Call `registry.register_tool` while supporting both historic
    `(name, func, metadata=None)` and new
    `(func=…, name=…, namespace=…, metadata=…)` signatures.
    """
    if not hasattr(registry, "register_tool"):
        logger.debug("Registry lacks register_tool – skip %s.%s", namespace, name)
        return

    try:
        sig = inspect.signature(registry.register_tool)  # type: ignore[attr-defined]
        if "func" in sig.parameters:                     # new API
            registry.register_tool(                     # type: ignore[call-arg]
                func=func,
                name=name,
                namespace=namespace,
                metadata=metadata,
            )
        else:                                           # legacy positional
            registry.register_tool(name, func, metadata)  # type: ignore[call-arg]
        logger.debug("→ %s.%s registered via ToolRegistryProvider", namespace, name)
    except Exception as exc:                            # noqa: BLE001
        logger.debug("ToolRegistryProvider.register_tool failed: %s", exc)


# ───────────────────────── factory ──────────────────────────
def create_proxy_tool(
    namespace: str,               # e.g.  "proxy.time"
    tool_name: str,               # e.g.  "get_current_time"
    stream_manager: Any,
    metadata: Optional[Any] = None,
    *,
    only_openai_tools: bool = False,
) -> Callable[..., Any]:
    """
    Return an async wrapper that forwards to the remote MCP tool.

    When *only_openai_tools* is **True** we still create the dot wrapper
    (because underscore wrappers delegate to it) but we no longer
    publish it to *ToolRegistryProvider*.
    """
    metadata = metadata or {}
    fq_name = f"{namespace}.{tool_name}"
    description = _meta_get(metadata, "description", f"Proxied tool: {fq_name}")
    server_name = namespace.split(".")[-1]

    # ------------------------------------------------------------------ #
    #   async wrapper – default-arg trick pins the values _now_          #
    # ------------------------------------------------------------------ #
    @mcp_tool(name=fq_name, description=description)
    async def _proxy_wrapper(
        __tool: str = tool_name,           # capture current value
        __server: str = server_name,       # capture current value
        **kwargs,
    ):
        logger.debug("Calling remote %s.%s with %s", __server, __tool, kwargs)

        result = await stream_manager.call_tool(
            tool_name=__tool,
            arguments=kwargs,
            server_name=__server,
        )

        if result.get("isError"):          # unified error envelope
            raise RuntimeError(result.get("error", "Unknown MCP error"))
        return result.get("content")

    # diagnostic / reflection helpers
    _proxy_wrapper._proxy_server   = server_name               # type: ignore[attr-defined]
    _proxy_wrapper._proxy_metadata = metadata                  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    #   optional ToolRegistryProvider registration                       #
    # ------------------------------------------------------------------ #
    if ToolRegistryProvider is not None and not only_openai_tools:
        _tp_register(
            ToolRegistryProvider.get_registry(),
            name=tool_name,
            namespace=namespace,
            func=_proxy_wrapper,
            metadata=metadata,
        )

    return _proxy_wrapper
