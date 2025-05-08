# chuk_mcp_runtime/entry.py
"""
Entry point for the CHUK MCP Runtime.

Starts the local MCP server *and* the optional proxy layer declared in the
configuration. Everything runs inside a single `asyncio` event‑loop so that
shutdown (Ctrl‑C / EOF) is graceful and predictable.
"""

from __future__ import annotations

import os
import sys
import asyncio
from typing import Any, List, Optional

from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.server.logging_config import configure_logging, get_logger
from chuk_mcp_runtime.server.server_registry import ServerRegistry
from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.proxy.manager import ProxyServerManager

logger = get_logger("chuk_mcp_runtime.entry")

# Flag to indicate if proxy support is available - always True in main code
# (tests will override this when they need to disable proxy)
HAS_PROXY_SUPPORT = True


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _need_proxy(config: dict[str, Any]) -> bool:
    """Return *True* if the `proxy` section is present *and* enabled and HAS_PROXY_SUPPORT is True."""
    return bool(config.get("proxy", {}).get("enabled", False)) and HAS_PROXY_SUPPORT


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────

def run_runtime(
    config_paths: Optional[List[str]] = None,
    default_config: Optional[dict[str, Any]] = None,
    bootstrap_components: bool = True,
) -> None:
    """Boot the complete CHUK MCP runtime **synchronously**.

    Parameters
    ----------
    config_paths
        Explicit YAML files.  ``None`` → fall back to the search logic in
        :pyfunc:`~chuk_mcp_runtime.server.config_loader.load_config`.
    default_config
        Baseline configuration merged under whatever the YAML provides.
    bootstrap_components
        If *True* (default) the runtime will import all tools / resources /
        prompts referenced in the configuration *before* the server starts.
    """
    # 1) ── configuration and logging ────────────────────────────────────
    config = load_config(config_paths, default_config)
    configure_logging(config)
    project_root = find_project_root()
    logger.debug("Project root resolved to %s", project_root)

    # 2) ── optional component bootstrap ────────────────────────────────
    if bootstrap_components and not os.getenv("NO_BOOTSTRAP"):
        ServerRegistry(project_root, config).load_server_components()

    # 3) ── async main coroutine that orchestrates proxy + server ───────
    async def _async_main() -> None:
        proxy_mgr = None

        # 3a) start proxy side‑cars if requested
        if _need_proxy(config):
            try:
                proxy_mgr = ProxyServerManager(config, project_root)
                await proxy_mgr.start_servers()
                if hasattr(proxy_mgr, 'running_servers') and proxy_mgr.running_servers:
                    logger.info(
                        "Proxy layer enabled – %d server(s) booted",
                        len(proxy_mgr.running_servers),
                    )
                    
                    # Register proxy tools with the MCP server
                    proxy_tools = proxy_mgr.get_all_tools()
                    if proxy_tools:
                        logger.info("Found %d proxy tools", len(proxy_tools))
            except Exception as e:
                logger.error(f"Error starting proxy layer: {e}", exc_info=True)
                proxy_mgr = None
        
        # 3b) Custom handler for proxy text processing
        custom_handlers = None
        if proxy_mgr and hasattr(proxy_mgr, 'process_text'):
            async def handle_proxy_text(text):
                try:
                    return await proxy_mgr.process_text(text)
                except Exception as e:
                    logger.error(f"Error processing proxy text: {e}", exc_info=True)
                    return [{"error": f"Proxy error: {str(e)}"}]
                    
            custom_handlers = {"handle_proxy_text": handle_proxy_text}

        # 3c) launch the local MCP server (stdio by default)
        mcp_server = MCPServer(config)
        
        # Safely log server name if available, for test compatibility
        if hasattr(mcp_server, 'server_name'):
            logger.info("Local MCP server '%s' starting", mcp_server.server_name)
        else:
            logger.info("Local MCP server starting")
        
        # If we have proxy tools, register them with the MCP server
        if proxy_mgr and hasattr(proxy_mgr, 'get_all_tools'):
            proxy_tools = proxy_mgr.get_all_tools()
            for tool_name, tool_func in proxy_tools.items():
                if hasattr(mcp_server, 'register_tool'):
                    try:
                        mcp_server.register_tool(tool_name, tool_func)
                        logger.debug(f"Registered proxy tool: {tool_name}")
                    except Exception as e:
                        logger.error(f"Error registering proxy tool {tool_name}: {e}")
        
        # Start the MCP server
        await mcp_server.serve(custom_handlers=custom_handlers)

        # 3d) tear down proxy side‑cars on shutdown
        if proxy_mgr is not None:
            logger.info("Stopping proxy layer")
            await proxy_mgr.stop_servers()

    # 4) ── run everything inside one fresh event‑loop ──────────────────
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.warning("Received Ctrl-C → shutting down")
    except Exception as exc:  # noqa: BLE001
        logger.error("Uncaught exception in runtime: %s", exc, exc_info=True)
        raise


def main(default_config: Optional[dict[str, Any]] = None) -> None:
    """Console entry point used by ``python -m chuk_mcp_runtime``.

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
        run_runtime(config_paths=config_paths, default_config=default_config)

    except Exception as exc:  # noqa: BLE001
        print(f"Error starting CHUK MCP server: {exc}", file=sys.stderr)
        sys.exit(1)


# Allow ``python -m chuk_mcp_runtime.entry`` for direct execution
if __name__ == "__main__":
    main()  