# chuk_mcp_runtime/server/server.py
"""
CHUK MCP Server Module

This module provides the core CHUK MCP server functionality for 
running tools and managing server operations.
"""
import asyncio
import json
import importlib
from typing import Dict, Any, List, Optional, Union, Callable

# MCP imports (assuming these are from an external package)
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource

# Local imports
from chuk_mcp_runtime.server.logging_config import get_logger

class MCPServer:
    """
    Manages the MCP (Messaging Control Protocol) server operations.
    
    Handles tool discovery, registration, and execution.
    """
    def __init__(self, config: Dict[str, Any], tools_registry: Optional[Dict[str, Callable]] = None):
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
        self.tools_registry = tools_registry or self._import_tools_registry()
    
    def _import_tools_registry(self) -> Dict[str, Callable]:
        """
        Dynamically import the tools registry.
        
        Returns:
            Dictionary of available tools.
        """
        # Get registry module path from config
        registry_module_path = self.config.get("tools", {}).get(
            "registry_module", "chuk_mcp_runtime.common.mcp_tool_decorator"
        )
        registry_attr = self.config.get("tools", {}).get(
            "registry_attr", "TOOLS_REGISTRY"
        )
        
        try:
            tools_decorator_module = importlib.import_module(registry_module_path)
            tools_registry = getattr(tools_decorator_module, registry_attr, {})
        except (ImportError, AttributeError) as e:
            self.logger.error(f"Failed to import TOOLS_REGISTRY from {registry_module_path}: {e}")
            tools_registry = {}
        
        if not tools_registry:
            self.logger.warning("No tools available")
        else:
            self.logger.info(f"Loaded {len(tools_registry)} tools")
            self.logger.debug(f"Available tools: {', '.join(tools_registry.keys())}")
        
        return tools_registry
    
    async def serve(self, custom_handlers: Optional[Dict[str, Callable]] = None) -> None:
        """
        Run the MCP server with stdio communication.
        
        Sets up server, tool listing, and tool execution handlers.
        
        Args:
            custom_handlers: Optional dictionary of custom handlers to add to the server.
        """
        # Create MCP server instance
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
            
            tool_list = []
            for func in self.tools_registry.values():
                if hasattr(func, '_mcp_tool'):
                    tool_list.append(func._mcp_tool)
            
            return tool_list

        @server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
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
            if name not in self.tools_registry:
                raise ValueError(f"Tool not found: {name}")
            
            func = self.tools_registry[name]
            try:
                self.logger.info(f"Executing tool '{name}' with arguments: {arguments}")
                result = func(**arguments)
                
                # If result is already a list of content objects, return as is
                if isinstance(result, list) and all(isinstance(item, (TextContent, ImageContent, EmbeddedResource)) 
                                                for item in result):
                    return result
                
                # For simple text results, wrap in TextContent
                if isinstance(result, str):
                    return [TextContent(type="text", text=result)]
                
                # Otherwise, serialize to JSON
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
                
            except Exception as e:
                self.logger.error(f"Error processing tool '{name}': {e}", exc_info=True)
                raise ValueError(f"Error processing tool '{name}': {str(e)}")
        
        # Add custom handlers if provided
        if custom_handlers:
            for handler_name, handler_func in custom_handlers.items():
                self.logger.info(f"Adding custom handler: {handler_name}")
                setattr(server, handler_name, handler_func)

        # Create initialization options
        options = server.create_initialization_options()
        
        # Run server based on configuration
        server_type = self.config.get("server", {}).get("type", "stdio")
        
        if server_type == "stdio":
            self.logger.info("Starting stdio server")
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, options)
        elif server_type == "websocket":
            # Example for websocket server - replace with actual implementation
            ws_host = self.config.get("server", {}).get("host", "localhost")
            ws_port = self.config.get("server", {}).get("port", 8080)
            self.logger.info(f"Starting WebSocket server on {ws_host}:{ws_port}")
            # Implement WebSocket server here
            raise NotImplementedError("WebSocket server not implemented yet")
        else:
            raise ValueError(f"Unknown server type: {server_type}")

    def register_tool(self, name: str, func: Callable) -> None:
        """
        Register a tool function with the server.
        
        Args:
            name: Name of the tool.
            func: Function to register.
        """
        if not hasattr(func, '_mcp_tool'):
            self.logger.warning(f"Function {func.__name__} does not have _mcp_tool attribute")
            return
            
        self.tools_registry[name] = func
        self.logger.info(f"Registered tool: {name}")
        
    def get_tool_names(self) -> List[str]:
        """
        Get names of all registered tools.
        
        Returns:
            List of tool names.
        """
        return list(self.tools_registry.keys())