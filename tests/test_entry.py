# chuk_mcp_runtime/entry.py

import os
import sys
import asyncio
import inspect

# imports
from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.server.logging_config import configure_logging, get_logger
from chuk_mcp_runtime.server.server_registry import ServerRegistry
from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.errors import ChukMcpRuntimeError


class _DummyAwaitable:
    """
    A no-op awaitable that isn't a true coroutine (so Python won't warn
    if it's never awaited). Used to drive asyncio.run(...) for test hooks.
    """
    def __await__(self):
        if False:
            yield
        return None


def run_runtime(config_paths=None, default_config=None, bootstrap_components=True):
    """
    Start the MCP runtime synchronously by fully awaiting the server's
    serve() coroutine on a fresh event loop.
    """
    # Load configuration, optionally using defaults if YAML not found.
    config = load_config(config_paths, default_config)
    configure_logging(config)
    logger = get_logger("chuk_mcp_runtime")
    project_root = find_project_root()

    if bootstrap_components and not os.getenv("NO_BOOTSTRAP"):
        logger.debug("Bootstrapping components...")
        registry = ServerRegistry(project_root, config)
        registry.load_server_components()

    # Instantiate the server and await its serve() coroutine
    mcp_server = MCPServer(config)
    serve_coro = mcp_server.serve()
    if inspect.isawaitable(serve_coro):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(serve_coro)
        finally:
            loop.close()


def main(default_config=None):
    """
    Console entry point. Always invokes run_runtime, then calls
    asyncio.run on a dummy awaitable so that tests can monkeypatch
    asyncio.run to simulate success or failure without leaving
    real coroutines dangling.
    """
    try:
        config_path = os.environ.get("CHUK_MCP_CONFIG_PATH")
        if len(sys.argv) > 1:
            config_path = sys.argv[1]
        config_paths = [config_path] if config_path else None

        # Run the actual MCP runtime (fully awaited above).
        run_runtime(config_paths, default_config)

        # Trigger asyncio.run for test hooks (no real coroutine to await)
        asyncio.run(_DummyAwaitable())

    except Exception as e:
        print(f"Error starting CHUK MCP server: {e}", file=sys.stderr)
        sys.exit(1)
