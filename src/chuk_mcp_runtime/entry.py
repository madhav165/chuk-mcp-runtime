# chuk_mcp_runtime/entry.py
"""
Entry point for the CHUK MCP Runtime.

Starts the local MCP server *and* the optional proxy layer declared in the
configuration. Everything runs inside a single `asyncio` event-loop so that
shutdown (Ctrl-C / EOF) is graceful and predictable.

Fully async-native implementation.
"""
from __future__ import annotations

import os
import sys
import asyncio
from inspect import iscoroutinefunction
from typing import Any, List, Optional

from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.server.logging_config import configure_logging, get_logger
from chuk_mcp_runtime.server.server_registry import ServerRegistry
from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_mcp_runtime.common.mcp_tool_decorator import initialize_tool_registry
from chuk_mcp_runtime.common.openai_compatibility import (
    initialize_openai_compatibility,
)

logger = get_logger("chuk_mcp_runtime.entry")

# tests may override this
HAS_PROXY_SUPPORT = True


def _need_proxy(config: dict[str, Any]) -> bool:
    """Return True when the YAML requests a proxy *and* proxy support is compiled in."""
    return bool(config.get("proxy", {}).get("enabled", False)) and HAS_PROXY_SUPPORT


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────
async def run_runtime_async(
    config_paths: Optional[List[str]] = None,
    default_config: Optional[dict[str, Any]] = None,
    bootstrap_components: bool = True,
) -> None:
    """Boot the complete CHUK MCP runtime **asynchronously**."""
    # 1) ── configuration and logging ────────────────────────────────────
    config = load_config(config_paths, default_config)
    configure_logging(config)
    project_root = find_project_root()
    logger.debug("Project root resolved to %s", project_root)

    # 2) ── optional component bootstrap ────────────────────────────────
    if bootstrap_components and not os.getenv("NO_BOOTSTRAP"):
        registry = ServerRegistry(project_root, config)
        await registry.load_server_components()

    # 3) ── initialise local tools and create OpenAI-style aliases ──────
    await initialize_tool_registry()

    # The wrapper generator may be monkey-patched to a non-awaitable
    try:
        if callable(initialize_openai_compatibility):
            if iscoroutinefunction(initialize_openai_compatibility):
                await initialize_openai_compatibility()
            else:
                initialize_openai_compatibility()
    except Exception as exc:  # pragma: no cover
        logger.warning("OpenAI-compat wrapper init failed: %s", exc)

    # 4) ── start proxy layer if requested ───────────────────────────────
    proxy_mgr = None
    if _need_proxy(config):
        try:
            proxy_mgr = ProxyServerManager(config, project_root)
            await proxy_mgr.start_servers()
            running = len(getattr(proxy_mgr, "running", {}))
            if running:
                logger.info("Proxy layer enabled – %d server(s) booted", running)
        except Exception as e:
            logger.error("Error starting proxy layer: %s", e, exc_info=True)
            proxy_mgr = None

    # 5) ── optional proxy text handler ──────────────────────────────────
    custom_handlers = None
    if proxy_mgr and hasattr(proxy_mgr, "process_text"):

        async def handle_proxy_text(text):
            try:
                return await proxy_mgr.process_text(text)
            except Exception as e:
                logger.error("Error processing proxy text: %s", e, exc_info=True)
                return [{"error": f"Proxy error: {e}"}]

        custom_handlers = {"handle_proxy_text": handle_proxy_text}

    # 6) ── launch local MCP server ──────────────────────────────────────
    mcp_server = MCPServer(config)
    logger.info("Local MCP server '%s' starting", getattr(mcp_server, "server_name", ""))

    if proxy_mgr and hasattr(proxy_mgr, "get_all_tools"):
        for tname, tfunc in (await proxy_mgr.get_all_tools()).items():
            try:
                await mcp_server.register_tool(tname, tfunc)
            except Exception as e:
                logger.error("Error registering proxy tool %s: %s", tname, e)

    try:
        await mcp_server.serve(custom_handlers=custom_handlers)
    finally:
        if proxy_mgr is not None:
            logger.info("Stopping proxy layer")
            await proxy_mgr.stop_servers()


# run_runtime(), main_async(), main() remain unchanged …

def run_runtime(
    config_paths: Optional[List[str]] = None,
    default_config: Optional[dict[str, Any]] = None,
    bootstrap_components: bool = True,
) -> None:
    """Boot the complete CHUK MCP runtime **synchronously**.

    This is a wrapper around run_runtime_async that sets up an event loop.

    Parameters
    ----------
    config_paths
        Explicit YAML files. ``None`` → fall back to the search logic in
        :pyfunc:`~chuk_mcp_runtime.server.config_loader.load_config`.
    default_config
        Baseline configuration merged under whatever the YAML provides.
    bootstrap_components
        If *True* (default) the runtime will import all tools / resources /
        prompts referenced in the configuration *before* the server starts.
    """
    try:
        asyncio.run(run_runtime_async(
            config_paths=config_paths,
            default_config=default_config,
            bootstrap_components=bootstrap_components
        ))
    except KeyboardInterrupt:
        logger.warning("Received Ctrl-C → shutting down")
    except Exception as exc:
        logger.error("Uncaught exception in runtime: %s", exc, exc_info=True)
        raise


async def main_async(default_config: Optional[dict[str, Any]] = None) -> None:
    """Async console entry point used by ``python -m chuk_mcp_runtime``.

    Environment / CLI precedence for the configuration path:

    1. first positional argument
    2. ``$CHUK_MCP_CONFIG_PATH``
    3. fall back to default search locations inside *load_config()*
    """
    try:
        # ── determine YAML to load ──────────────────────────────────
        config_path = os.environ.get("CHUK_MCP_CONFIG_PATH")
        if len(sys.argv) > 1:
            config_path = sys.argv[1]

        config_paths = [config_path] if config_path else None

        # ── start runtime (never returns unless there is an error) ──
        await run_runtime_async(config_paths=config_paths, default_config=default_config)

    except Exception as exc:
        print(f"Error starting CHUK MCP server: {exc}", file=sys.stderr)
        sys.exit(1)


def main(default_config: Optional[dict[str, Any]] = None) -> None:
    """Console entry point used by ``python -m chuk_mcp_runtime``.

    This is a wrapper around main_async that sets up an event loop.
    """
    try:
        asyncio.run(main_async(default_config=default_config))
    except KeyboardInterrupt:
        logger.warning("Received Ctrl-C → shutting down")
    except Exception as exc:
        logger.error("Uncaught exception in runtime: %s", exc, exc_info=True)
        sys.exit(1)


# Allow ``python -m chuk_mcp_runtime.entry`` for direct execution
if __name__ == "__main__":
    main()