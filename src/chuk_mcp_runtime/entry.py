# chuk_mcp_runtime/entry.py
import os
import sys
import asyncio

# imports
from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.server.logging_config import configure_logging, get_logger
from chuk_mcp_runtime.server.server_registry import ServerRegistry
from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.errors import ChukMcpRuntimeError

async def run_runtime(config_paths=None, default_config=None, bootstrap_components=True):
    # Load configuration, optionally using defaults if YAML not found.
    config = load_config(config_paths, default_config)
    configure_logging(config)
    logger = get_logger("chuk_mcp_runtime")
    project_root = find_project_root()

    if bootstrap_components and not os.getenv("NO_BOOTSTRAP"):
        logger.info("Bootstrapping components...")
        registry = ServerRegistry(project_root, config)
        registry.load_server_components()

    mcp_server = MCPServer(config)
    await mcp_server.serve()

def main(default_config=None):
    try:
        config_path = os.environ.get("CHUK_MCP_CONFIG_PATH")
        if len(sys.argv) > 1:
            config_path = sys.argv[1]
        config_paths = [config_path] if config_path else None
        asyncio.run(run_runtime(config_paths, default_config))
    except Exception as e:
        print(f"Error starting CHUK MCP server: {e}", file=sys.stderr)
        sys.exit(1)
