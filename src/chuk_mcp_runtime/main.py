# chuk_mcp_runtime/main.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CHUK MCP Runtime Main Entry
===========================

Main entry point for the CHUK MCP runtime. This module is the primary
entry point when the package is run directly via `python -m chuk_mcp_runtime`
or when using the console scripts defined in setup.py.

Example usage:
    python -m chuk_mcp_runtime            # Use default config paths
    python -m chuk_mcp_runtime config.yml # Use specific config file
    CHUK_MCP_CONFIG_PATH=/etc/chuk/config.yaml python -m chuk_mcp_runtime
"""
from __future__ import annotations

import sys
import argparse
from typing import List, Optional

from chuk_mcp_runtime.entry import main, run_runtime
from chuk_mcp_runtime.server.config_loader import load_config
from chuk_mcp_runtime.server.logging_config import get_logger


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """
    Parse command line arguments.
    
    Args:
        args: Command line arguments (defaults to sys.argv[1:])
        
    Returns:
        Parsed arguments as Namespace object
    """
    parser = argparse.ArgumentParser(
        description="CHUK MCP Runtime Server",
        epilog="Environment variables: CHUK_MCP_CONFIG_PATH, CHUK_MCP_LOG_LEVEL, NO_BOOTSTRAP"  
    )
    
    parser.add_argument(
        "config_file", 
        nargs="?", 
        help="Path to config file (overrides CHUK_MCP_CONFIG_PATH)"
    )
    
    parser.add_argument(
        "--no-bootstrap", 
        action="store_true",
        help="Skip component bootstrapping"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set logging level (overrides config and CHUK_MCP_LOG_LEVEL)"
    )
    
    parser.add_argument(
        "--version", 
        action="store_true",
        help="Show version information and exit"
    )
    
    return parser.parse_args(args)


def cli_main() -> None:
    """
    Command-line entry point with argument parsing.
    """
    args = parse_args()
    
    # Handle version request
    if args.version:
        from chuk_mcp_runtime import __version__
        print(f"CHUK MCP Runtime v{__version__}")
        sys.exit(0)
    
    # Prepare default config with command line overrides
    default_config = {}
    if args.log_level:
        default_config["logging"] = {"level": args.log_level}
    
    # Run with specified config file
    config_paths = [args.config_file] if args.config_file else None
    run_runtime(
        config_paths=config_paths,
        default_config=default_config,
        bootstrap_components=not args.no_bootstrap
    )


if __name__ == "__main__":
    # Use enhanced CLI entry point when run directly
    cli_main()
else:
    # Keep simple entry point for backwards compatibility when imported
    main()