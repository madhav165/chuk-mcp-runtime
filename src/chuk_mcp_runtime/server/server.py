# chuk_mcp_runtime/server/server.py
"""
CHUK MCP Server Module - Async Native Implementation

This module provides the core CHUK MCP server functionality for 
running tools and managing server operations.
"""
import asyncio
import json
import inspect
import importlib
from typing import Dict, Any, List, Optional, Union, Callable
import re

# MCP imports (assuming these are from an external package)
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import Response, JSONResponse
from starlette.requests import Request
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware import Middleware
import uvicorn

# Local imports
from chuk_mcp_runtime.server.logging_config import get_logger
from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY, initialize_tool_registry
from chuk_mcp_runtime.common.verify_credentials import validate_token
from chuk_mcp_runtime.common.tool_naming import resolve_tool_name, update_naming_maps

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders
from typing import Callable


class AuthMiddleware:
    """Auth middleware"""
    def __init__(self, app: ASGIApp, auth: str = None):
        self.app = app
        self.auth = auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or self.auth is None:
            return await self.app(scope, receive, send)

        request = Request(scope, receive=receive)
        headers = MutableHeaders(scope=scope)
        token = None

        # Get token from Authorization header
        if self.auth == "bearer":
            if "Authorization" in headers:
                match = re.match(
                    r"Bearer\s+(.+)",
                    headers.get("Authorization"),
                    re.IGNORECASE
                )
                if match:
                    token = match.group(1)
                else:
                    token = ""
            else:
                token = ""

            # Try token from cookies
            if not token:
                token = request.cookies.get("jwt_token")

        if not token:
            response = JSONResponse(
                {"error": "Not authenticated"},
                status_code=401
            )
            return await response(scope, receive, send)

        # Validate token
        try:
            payload = await validate_token(token)
            scope["user"] = payload
            # return await response(scope, receive, send)
        except HTTPException as ex:
            response = JSONResponse(
                {"error": ex.detail},
                status_code=ex.status_code
            )
            return await response(scope, receive, send)

        # Auth OK, pass to app
        await self.app(scope, receive, send)


class MCPServer:
    """
    Manages the MCP (Messaging Control Protocol) server operations.
    
    Handles tool discovery, registration, and execution.
    """
    def __init__(
        self,
        config: Dict[str, Any],
        tools_registry: Optional[Dict[str, Callable]] = None
    ):
        """
        Initialize the MCP server.
        
        Args:
            config: Configuration dictionary for the server.
            tools_registry: Optional registry of tools to use instead of importing.
        """
        self.config = config
        
        # Initialize logger
        self.logger = get_logger("chuk_mcp_runtime.server", config)
        
        # Server name from configuration
        self.server_name = config.get("host", {}).get("name", "generic-mcp")
        
        # Tools registry
        self.tools_registry = tools_registry or TOOLS_REGISTRY
        
        # Update the tool naming maps to ensure resolution works correctly
        update_naming_maps()
    
    async def _import_tools_registry(self) -> Dict[str, Callable]:
        """
        Dynamically import the tools registry.
        
        Returns:
            Dictionary of available tools.
        """
        registry_module_path = self.config.get(
            "tools", {}
        ).get(
            "registry_module",
            "chuk_mcp_runtime.common.mcp_tool_decorator"
        )
        registry_attr = self.config.get(
            "tools", {}
        ).get(
            "registry_attr",
            "TOOLS_REGISTRY"
        )
        
        try:
            tools_decorator_module = importlib.import_module(registry_module_path)
            tools_registry = getattr(tools_decorator_module, registry_attr, {})
            
            # Initialize any tools that need it
            if hasattr(tools_decorator_module, 'initialize_tool_registry'):
                await tools_decorator_module.initialize_tool_registry()
        except (ImportError, AttributeError) as e:
            self.logger.error(
                f"Failed to import TOOLS_REGISTRY from {registry_module_path}: {e}"
            )
            tools_registry = {}
        
        if not tools_registry:
            self.logger.warning("No tools available")
        else:
            self.logger.debug(f"Loaded {len(tools_registry)} tools")
            self.logger.debug(f"Available tools: {', '.join(tools_registry.keys())}")
        
        # Update naming maps after importing tools
        update_naming_maps()
        
        return tools_registry
    
    async def serve(self, custom_handlers: Optional[Dict[str, Callable]] = None) -> None:
        """
        Run the MCP server with stdio communication.
        
        Sets up server, tool listing, and tool execution handlers.
        
        Args:
            custom_handlers: Optional dictionary of custom handlers to add to the server.
        """
        # Ensure tools registry is initialized
        if not self.tools_registry:
            self.tools_registry = await self._import_tools_registry()
        
        # Initialize any tool placeholders
        await initialize_tool_registry()
        
        # Update naming maps after initializing tools
        update_naming_maps()
            
        server = Server(self.server_name)

        @server.list_tools()
        async def list_tools() -> List[Tool]:
            """
            List available tools.
            
            Returns:
                List of tool descriptions.
            """
            if not self.tools_registry:
                self.logger.warning("No tools available")
                return []
            
            return [
                func._mcp_tool
                for func in self.tools_registry.values()
                if hasattr(func, '_mcp_tool')
            ]

        @server.call_tool()
        async def call_tool(
            name: str,
            arguments: Dict[str, Any]
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            """
            Execute a tool.

            Typical CLI calls deliver exactly the registered tool name
            (e.g. ``duckduckgo_search``).  But when the CLI uses the
            “server.tool” syntax, the front-end splits that into
            ``server = duckduckgo`` and ``name = search`` before it
            reaches us.  That used to raise “Tool 'search' not found”.

            The resolver below tries four strategies in order:

            1. direct lookup                           (fast path)
            2. compatibility-mapper (`resolve_tool_name`)
            3. *unique* suffix match  “…_{name}”
            4. *unique* suffix match  “….{name}”

            If more than one candidate matches a suffix we *fail fast*
            with a clear error so ambiguity is never silent.
            """
            registry = self.tools_registry

            # 1) direct hit
            if name in registry:
                resolved = name
            else:
                # 2) smart resolver (dot <-> underscore table)
                resolved = resolve_tool_name(name)

                # 3 / 4) last-chance suffix search
                if resolved not in registry:
                    matches = [
                        k for k in registry
                        if k.endswith(f"_{name}") or k.endswith(f".{name}")
                    ]
                    if len(matches) == 1:
                        resolved = matches[0]

            if resolved not in registry:
                raise ValueError(f"Tool not found: {name}")

            func = registry[resolved]
            self.logger.debug("Executing '%s' with %s", resolved, arguments)
            try:
                result = await func(**arguments)
            except Exception as exc:
                self.logger.error("Tool '%s' failed: %s", resolved, exc, exc_info=True)
                raise ValueError(f"Error processing tool '{resolved}': {exc}") from exc

            # ---------- normalise result to MCP content ----------
            if (
                isinstance(result, list)
                and all(isinstance(r, (TextContent, ImageContent, EmbeddedResource)) for r in result)
            ):
                return result

            if isinstance(result, str):
                return [TextContent(type="text", text=result)]

            return [TextContent(type="text", text=json.dumps(result, indent=2))]


    async def register_tool(self, name: str, func: Callable) -> None:
        """
        Register a tool function with the server.
        
        Args:
            name: Name of the tool.
            func: Function to register.
        """
        if not hasattr(func, '_mcp_tool'):
            self.logger.warning(f"Function {func.__name__} lacks _mcp_tool metadata")
            return
            
        self.tools_registry[name] = func
        self.logger.debug(f"Registered tool: {name}")
        
        # Update naming maps after registering a new tool
        update_naming_maps()
        
    async def get_tool_names(self) -> List[str]:
        """
        Get names of all registered tools.
        
        Returns:
            List of tool names.
        """
        return list(self.tools_registry.keys())