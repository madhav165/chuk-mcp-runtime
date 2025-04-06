# chuk_mcp_runtime/main.py
import os
import sys
import asyncio
from typing import Dict, Any, Optional, List

from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.server.logging_config import get_logger, configure_logging
from chuk_mcp_runtime.server.server_registry import ServerRegistry
from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.common.errors import ChukMcpRuntimeError

async def run_server(config_paths: Optional[List[str]] = None, 
                    default_config: Optional[Dict[str, Any]] = None) -> None:
    """
    Initialize and run an MCP server with the given configuration.
    
    Args:
        config_paths: List of paths to search for configuration files.
        default_config: Default configuration to use if no config file is found.
        
    Raises:
        ConfigurationError: If there is an error in the configuration.
    """
    try:
        # Load configuration
        config = load_config(config_paths, default_config)
        
        # Configure logging
        configure_logging(config)
        logger = get_logger("chuk_mcp_runtime")
        
        # Find project root
        project_root = find_project_root()
        
        # Initialize server registry
        logger.info("Initializing server registry")
        server_registry = ServerRegistry(project_root, config)
        
        # Load server components
        logger.info("Loading server components")
        loaded_modules = server_registry.load_server_components()
        
        # Initialize MCP server
        logger.info("Initializing MCP server")
        mcp_server = MCPServer(config)
        
        # Run server
        logger.info("Starting MCP server")
        await mcp_server.serve()
        
    except Exception as e:
        logger = get_logger("chuk_mcp_runtime")
        logger.error(f"Error starting CHUK MCP server: {e}", exc_info=True)
        raise ChukMcpRuntimeError(f"Error starting CHUK MCP server: {e}")

def main():
    """
    Entry point for the MCP runtime command-line script.
    """
    try:
        # Get configuration path from environment or command line
        config_path = os.environ.get("CHUK_MCP_CONFIG_PATH")
        if len(sys.argv) > 1:
            config_path = sys.argv[1]
            
        config_paths = [config_path] if config_path else None
        
        # Run the server
        asyncio.run(run_server(config_paths))
    except Exception as e:
        print(f"Error starting CHUK MCP server: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()