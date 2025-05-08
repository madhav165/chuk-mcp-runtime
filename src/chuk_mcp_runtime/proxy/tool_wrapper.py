# chuk_mcp_runtime/server/tool_wrapper.py
"""
chuk_mcp_runtime.proxy.tool_wrapper
===================================

Turn *every* remote MCP tool into a local async wrapper that can be
called as

    <proxy_namespace>.<server_name>.<tool_name>

The wrapper is registered in

1. chuk_mcp_runtime.common.TOOLS_REGISTRY      (via @mcp_tool)
2. ToolRegistryProvider                        (only if it exposes
   `register_tool(func, name=…, namespace=…, metadata=…)`)
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from chuk_mcp_runtime.server.logging_config import get_logger

try:
    from chuk_tool_processor.registry import ToolRegistryProvider
except ModuleNotFoundError:  # ToolProcessor not installed in some envs
    ToolRegistryProvider = None  # type: ignore

logger = get_logger("chuk_mcp_runtime.proxy.tool_wrapper")


# ───────────────────────── helpers ──────────────────────────────────
def _meta_get(meta: Any, key: str, default: Any) -> Any:
    """meta may be dict or Pydantic model – fetch *key* safely."""
    return meta.get(key, default) if isinstance(meta, dict) else getattr(meta, key, default)


def _registry_add(
    registry: Any,
    namespace: str,
    name: str,
    func: Callable[..., Any],
    metadata: Any,
) -> None:
    """
    Register *func* in ToolRegistryProvider using **one** signature:

        registry.register_tool(
            func,
            name=name,
            namespace=namespace,
            metadata=metadata,
        )
    """
    if not hasattr(registry, "register_tool"):
        logger.debug("ToolRegistryProvider lacks register_tool – skipping %s.%s", namespace, name)
        return

    registry.register_tool(
        func,
        name=name,
        namespace=namespace,
        metadata=metadata,
    )
    logger.debug("→ %s.%s registered via register_tool(func,…)", namespace, name)


# ───────────────────────── factory ──────────────────────────────────
def create_proxy_tool(
    namespace: str,
    tool_name: str,
    stream_manager: Any,
    metadata: Optional[Any] = None,
):
    """
    Wrap a remote MCP tool so it can be called locally.

    Parameters
    ----------
    namespace : str
        Proxy namespace incl. server (e.g. ``proxy.echo2``).
    tool_name : str
        Remote tool name (e.g. ``echo``).
    stream_manager : StreamManager
        Provides the transport to the remote server.
    metadata : dict | ToolMetadata | None
        Extra info (description, schemas, …) from the remote.

    Returns
    -------
    Callable[..., Any]
        Async function that executes the remote tool.
    """
    metadata = metadata or {}
    fq_name = f"{namespace}.{tool_name}"
    description = _meta_get(metadata, "description", f"Proxied tool: {fq_name}")
    server_name = namespace.split(".")[-1]

    # ------------------------------------------------------------------
    # async wrapper – added to TOOLS_REGISTRY via decorator
    # ------------------------------------------------------------------
    @mcp_tool(name=fq_name, description=description)
    async def proxy_tool_wrapper(**kwargs):
        logger.debug("Calling remote %s with %s", fq_name, kwargs)

        # StreamManager chooses the correct transport under the hood
        result_packet = await stream_manager.call_tool(
            tool_name=tool_name,
            arguments=kwargs,
            server_name=server_name,
        )

        if result_packet.get("isError"):  # unified error shape
            raise RuntimeError(result_packet.get("error", "Unknown MCP error"))

        return result_packet.get("content")

    # diagnostics for debugging / reflection
    proxy_tool_wrapper._proxy_metadata = metadata           # type: ignore[attr-defined]
    proxy_tool_wrapper._proxy_server = server_name          # type: ignore[attr-defined]
    proxy_tool_wrapper._proxy_namespace = namespace         # type: ignore[attr-defined]

    logger.debug("→ %s registered in TOOLS_REGISTRY", fq_name)

    # secondary registration (if registry supports our one API)
    if ToolRegistryProvider is not None:
        reg = ToolRegistryProvider.get_registry()
        if (namespace, tool_name) not in reg.list_tools():
            _registry_add(reg, namespace, tool_name, proxy_tool_wrapper, metadata)

    return proxy_tool_wrapper
