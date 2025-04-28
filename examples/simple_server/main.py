# examples/simple_server/main.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple CHUK MCP Server Example
==============================

This example demonstrates how to create a simple CHUK MCP server
with an "echo" tool and expose it over SSE.
"""
import logging
import os
import sys
from typing import Dict, Any

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Import the CHUK MCP runtime
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from chuk_mcp_runtime.entry import run_runtime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("chuk_mcp_runtime.chuk_example_server")

# Define a simple echo tool
@mcp_tool(name="echo", description="Echo the input message back to the sender")
def echo_tool(message: str = "Hello world!") -> str:
    """Echo the input message back to the sender."""
    logger.info(f"Echo tool received: {message}")
    return f"You said: {message}"

# Configuration for the server
config: Dict[str, Any] = {
    "host": {
        "name": "chuk-example-server",
        "log_level": "INFO"
    },
    "server": {
        "type": "sse"  # Use SSE server instead of stdio
    },
    "sse": {
        "host": "127.0.0.1",
        "port": 8000,
        "sse_path": "/sse",
        "message_path": "/messages",
        "log_level": "info"
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "reset_handlers": True
    }
}

if __name__ == "__main__":
    logger.info("Starting example CHUK MCP server")
    run_runtime(default_config=config, bootstrap_components=False)