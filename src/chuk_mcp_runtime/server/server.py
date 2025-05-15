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
            Execute a specific tool with given arguments.
            
            Args:
                name: Name of the tool to execute.
                arguments: Arguments for the tool.
            
            Returns:
                List of content resulting from tool execution.
            
            Raises:
                ValueError: If tool is not found or fails to execute.
            """
            # Resolve tool name using the compatibility layer
            resolved_name = resolve_tool_name(name)
            
            if resolved_name != name:
                self.logger.debug(f"Resolved tool name '{name}' to '{resolved_name}'")
            
            if resolved_name not in self.tools_registry:
                raise ValueError(f"Tool not found: {name} (resolved to {resolved_name})")
            
            func = self.tools_registry[resolved_name]
            try:
                self.logger.debug(f"Executing tool '{resolved_name}' with arguments: {arguments}")
                
                # Execute the tool (should always be async)
                result = await func(**arguments)
                
                # If result is already content objects, return as is
                if (
                    isinstance(result, list)
                    and all(
                        isinstance(item, (TextContent, ImageContent, EmbeddedResource))
                        for item in result
                    )
                ):
                    return result
                
                # If it's a simple string, wrap in TextContent
                if isinstance(result, str):
                    return [TextContent(type="text", text=result)]
                
                # Otherwise, serialize to JSON and wrap
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, indent=2)
                    )
                ]
                
            except Exception as e:
                self.logger.error(
                    f"Error processing tool '{resolved_name}': {e}", exc_info=True
                )
                raise ValueError(f"Error processing tool '{resolved_name}': {str(e)}")
        
        # Add any custom handlers
        if custom_handlers:
            for handler_name, handler_func in custom_handlers.items():
                self.logger.debug(f"Adding custom handler: {handler_name}")
                setattr(server, handler_name, handler_func)

        options = server.create_initialization_options()
        server_type = self.config.get("server", {}).get("type", "stdio")
        
        if server_type == "stdio":
            self.logger.info("Starting stdio server")
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, options)
        elif server_type == "sse":
            self.logger.info("Starting MCP server over SSE")
            # Get SSE server configuration
            sse_config = self.config.get("sse", {})
            host = sse_config.get("host", "127.0.0.1")
            port = sse_config.get("port", 8000)
            sse_path = sse_config.get("sse_path", "/sse")
            msg_path = sse_config.get("message_path", "/messages/")
            
            # Create the starlette app with routes
            # Create the SSE transport instance
            sse_transport = SseServerTransport(msg_path)
            
            async def handle_sse(request: Request):
                async with sse_transport.connect_sse(
                    request.scope,
                    request.receive,
                    request._send
                ) as streams:
                    await server.run(streams[0], streams[1], options)
                # Return empty response to avoid NoneType error
                return Response()
            
            routes = [
                Route(sse_path, endpoint=handle_sse, methods=["GET"]),
                Mount(msg_path, app=sse_transport.handle_post_message),
            ]
            
            starlette_app = Starlette(routes=routes)
            
            starlette_app.add_middleware(
                AuthMiddleware,
                auth=self.config.get("server", {}).get("auth", None)
            )
            
            # uvicorn.run(starlette_app, host="0.0.0.0", port=port)
            config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
            uvicorn_server = uvicorn.Server(config)
            await uvicorn_server.serve()
        else:
            raise ValueError(f"Unknown server type: {server_type}")

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