# chuk-mcp-runtime/proxy/__init__.py
"""
CHUK MCP Runtime Proxy Package

This package provides proxy functionality for CHUK MCP Runtime,
allowing it to manage and communicate with other MCP servers.
"""

from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_mcp_runtime.proxy.tool_wrapper import create_proxy_tool

__all__ = [
    'ProxyServerManager',
    'create_proxy_tool'
]