# chuk_mcp_runtime/__init__.py
"""
CHUK MCP Runtime Package

This package provides a runtime for CHUK MCP (Messaging Control Protocol) servers
with integrated proxy support for connecting to remote MCP servers.
"""

__version__ = "0.1.0"

# Import key functions from entry module
# We avoid importing the entire entry module to prevent circular imports
from chuk_mcp_runtime.entry import run_runtime, main

__all__ = [
    'run_runtime',
    'main',
]