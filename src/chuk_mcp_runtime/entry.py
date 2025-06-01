# chuk_mcp_runtime/entry.py
"""
Entry point for the CHUK MCP Runtime – async-native, proxy-aware,
with automatic chuk_artifacts integration.
"""
from __future__ import annotations

import os
import sys
import asyncio
from inspect import iscoroutinefunction
from typing import Any, List, Optional, Iterable, Tuple

from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.server.logging_config import configure_logging, get_logger
from chuk_mcp_runtime.server.server_registry import ServerRegistry
from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_mcp_runtime.common.mcp_tool_decorator import (
    initialize_tool_registry,
    TOOLS_REGISTRY,                # ← global "name → wrapper" dict
)
from chuk_mcp_runtime.common.openai_compatibility import (
    initialize_openai_compatibility,
)
from chuk_mcp_runtime.tools import get_artifact_tools

logger = get_logger("chuk_mcp_runtime.entry")

# ────────────────────────────── chuk_artifacts support ─────────────────────
try:
    from chuk_mcp_runtime.tools import (
        register_artifacts_tools as _register_artifact_tools,
        ARTIFACTS_TOOLS_AVAILABLE as _ARTIFACTS_TOOLS_AVAILABLE,
    )

    async def register_artifact_tools(cfg: dict[str, Any]):
        await _register_artifact_tools(cfg)

    CHUK_ARTIFACTS_AVAILABLE = _ARTIFACTS_TOOLS_AVAILABLE
except ImportError:  # pragma: no cover – chuk_artifacts not installed
    CHUK_ARTIFACTS_AVAILABLE = False

    async def register_artifact_tools(_: dict[str, Any]):  # noqa: D401
        pass  # graceful no-op


HAS_PROXY_SUPPORT = True                        # tests may override


def _need_proxy(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("proxy", {}).get("enabled")) and HAS_PROXY_SUPPORT


# ────────────────────────────────────────────────────────────────────────────
# helper – resolve tools no matter the container type
# ────────────────────────────────────────────────────────────────────────────
def _iter_tools(container) -> Iterable[Tuple[str, Any]]:
    """
    Yield *(name, callable)* pairs from the object returned by
    ``get_artifact_tools()``.

    • **dict** – easy: items()
    • **list / tuple / set** – resolve *decorated wrappers* from
      `TOOLS_REGISTRY` first, fall back to the helper in `artifacts_tools`
    """
    from chuk_mcp_runtime.tools import artifacts_tools as _at_mod

    if container is None:
        return ()

    # dict → already {name: wrapper}
    if isinstance(container, dict):
        for name, func in container.items():
            if hasattr(func, "_mcp_tool"):
                yield name, func
            else:
                logger.debug("Tool %s ignored – no _mcp_tool metadata", name)
        return ()

    # list / tuple / set → need lookup
    if isinstance(container, (list, tuple, set)):
        for name in container:
            # 1) global registry (populated by the decorator)
            func = TOOLS_REGISTRY.get(name)
            # 2) fallback: attribute on artifacts_tools module
            if func is None:
                func = getattr(_at_mod, name, None)
            if func and hasattr(func, "_mcp_tool"):
                yield name, func
            else:
                logger.debug("Unable to resolve decorated tool '%s'", name)
        return ()

    logger.debug("Unexpected get_artifact_tools() return type: %s", type(container))
    return ()


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────
async def run_runtime_async(
    config_paths: Optional[List[str]] = None,
    default_config: Optional[dict[str, Any]] = None,
    bootstrap_components: bool = True,
) -> None:
    """Boot the complete CHUK MCP runtime (async)."""
    # 1. configuration + logging
    cfg = load_config(config_paths, default_config)
    configure_logging(cfg)
    project_root = find_project_root()
    logger.debug("Project root resolved to %s", project_root)

    # 2. optional component bootstrap
    if bootstrap_components and not os.getenv("NO_BOOTSTRAP"):
        await ServerRegistry(project_root, cfg).load_server_components()

    # 3. initialise decorator-based tool registry
    await initialize_tool_registry()

    # 4. chuk_artifacts wrappers
    if CHUK_ARTIFACTS_AVAILABLE:
        try:
            await register_artifact_tools(cfg)
            logger.info("chuk_artifacts tools registered successfully")
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to register chuk_artifacts tools: %s", exc)
    else:
        logger.info("chuk_artifacts not available – file tools skipped")

    # 5. optional OpenAI compatibility wrappers
    try:
        if callable(initialize_openai_compatibility):
            if iscoroutinefunction(initialize_openai_compatibility):
                await initialize_openai_compatibility()
            else:
                initialize_openai_compatibility()
    except Exception as exc:  # pragma: no cover
        logger.warning("OpenAI-compat wrapper init failed: %s", exc)

    # 6. proxy layer (if any)
    proxy_mgr = None
    if _need_proxy(cfg):
        try:
            proxy_mgr = ProxyServerManager(cfg, project_root)
            await proxy_mgr.start_servers()
            running = len(getattr(proxy_mgr, "running", {}))
            if running:
                logger.info("Proxy layer enabled – %d server(s) booted", running)
        except Exception as exc:  # pragma: no cover
            logger.error("Error starting proxy layer: %s", exc, exc_info=True)
            proxy_mgr = None

    # 7. MCP server - PASS THE POPULATED REGISTRY EXPLICITLY
    mcp_server = MCPServer(cfg, tools_registry=TOOLS_REGISTRY)
    logger.info("Local MCP server '%s' starting",
                getattr(mcp_server, "server_name", "local"))

    # Log the number of tools available
    tools_count = len(TOOLS_REGISTRY)
    artifact_tools = [name for name in TOOLS_REGISTRY.keys() if any(kw in name for kw in ['file', 'upload', 'write', 'read', 'list'])]
    logger.info("Tools available in registry: %d total, %d artifact-related", tools_count, len(artifact_tools))
    logger.debug("Available tools: %s", ', '.join(sorted(TOOLS_REGISTRY.keys())))

    # 7a. register artifact tools (this should now be redundant, but keeping for safety)
    for name, func in _iter_tools(get_artifact_tools()):
        try:
            await mcp_server.register_tool(name, func)
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to register tool %s: %s", name, exc)

    # 7b. proxy-exported tools
    if proxy_mgr and hasattr(proxy_mgr, "get_all_tools"):
        for name, func in (await proxy_mgr.get_all_tools()).items():
            try:
                await mcp_server.register_tool(name, func)
            except Exception as exc:  # pragma: no cover
                logger.error("Error registering proxy tool %s: %s", name, exc)

    # 7c. proxy text handler
    custom_handlers = None
    if proxy_mgr and hasattr(proxy_mgr, "process_text"):

        async def _handle_proxy_text(text: str):
            try:
                return await proxy_mgr.process_text(text)
            except Exception as exc:  # pragma: no cover
                logger.error("Proxy text-handler error: %s", exc, exc_info=True)
                return [{"error": f"Proxy error: {exc}"}]

        custom_handlers = {"handle_proxy_text": _handle_proxy_text}

    # 8. serve forever
    try:
        await mcp_server.serve(custom_handlers=custom_handlers)
    finally:
        if proxy_mgr:
            logger.info("Stopping proxy layer")
            await proxy_mgr.stop_servers()


# ───────────────────────── sync wrappers & CLI glue ─────────────────────────
def run_runtime(
    config_paths: Optional[List[str]] = None,
    default_config: Optional[dict[str, Any]] = None,
    bootstrap_components: bool = True,
) -> None:
    try:
        asyncio.run(
            run_runtime_async(
                config_paths=config_paths,
                default_config=default_config,
                bootstrap_components=bootstrap_components,
            )
        )
    except KeyboardInterrupt:
        logger.warning("Received Ctrl-C → shutting down")
    except Exception as exc:  # pragma: no cover
        logger.error("Uncaught exception: %s", exc, exc_info=True)
        raise


async def main_async(default_config: Optional[dict[str, Any]] = None) -> None:
    try:
        argv = sys.argv[1:]
        cfg_path = (
            os.getenv("CHUK_MCP_CONFIG_PATH")
            or (argv[argv.index("-c") + 1] if "-c" in argv else None)
            or (argv[argv.index("--config") + 1] if "--config" in argv else None)
            or (argv[0] if argv else None)
        )
        await run_runtime_async(
            config_paths=[cfg_path] if cfg_path else None,
            default_config=default_config,
        )
    except Exception as exc:  # pragma: no cover
        print(f"Error starting CHUK MCP server: {exc}", file=sys.stderr)
        sys.exit(1)


def main(default_config: Optional[dict[str, Any]] = None) -> None:
    try:
        asyncio.run(main_async(default_config))
    except KeyboardInterrupt:
        logger.warning("Received Ctrl-C → shutting down")
    except Exception as exc:  # pragma: no cover
        logger.error("Uncaught exception: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":  # python -m chuk_mcp_runtime.entry
    main()