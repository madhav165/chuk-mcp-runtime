# chuk_mcp_runtime/server/server.py
"""
CHUK MCP Server Module

This module provides the core CHUK MCP server functionality with
session context management, automatic session injection, and 
enhanced chuk_artifacts integration.

Simplified version - LLMs handle session context directly through tools.
"""
import asyncio
import json
import inspect
import importlib
from typing import Dict, Any, List, Optional, Union, Callable
import re

# MCP imports
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
from chuk_mcp_runtime.session.session_management import (
    set_session_context,
    get_session_context,
    clear_session_context,
    SessionError
)

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders
from typing import Callable

# Enhanced chuk_artifacts integration
try:
    from chuk_artifacts import ArtifactStore
    CHUK_ARTIFACTS_AVAILABLE = True
except ImportError:
    CHUK_ARTIFACTS_AVAILABLE = False
    ArtifactStore = None


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
    Manages the MCP (Messaging Control Protocol) server operations with session support
    and enhanced chuk_artifacts integration.
    
    Handles tool discovery, registration, execution, and session management.
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
        
        # Tools registry - prefer passed registry over global one
        if tools_registry is not None:
            self.tools_registry = tools_registry
            self.logger.debug(f"Using passed tools registry with {len(tools_registry)} tools")
        else:
            self.tools_registry = TOOLS_REGISTRY
            self.logger.debug(f"Using global tools registry with {len(TOOLS_REGISTRY)} tools")
        
        # Session management
        self.current_session: Optional[str] = None
        
        # Enhanced artifact store integration
        self.artifact_store: Optional[ArtifactStore] = None
        
        # Update the tool naming maps to ensure resolution works correctly
        update_naming_maps()
    
    async def _setup_artifact_store(self) -> None:
        """Setup the artifact store if chuk_artifacts is available."""
        if not CHUK_ARTIFACTS_AVAILABLE:
            self.logger.info("chuk_artifacts not available - file management disabled")
            return
        
        try:
            # Get artifact store configuration from config
            artifacts_config = self.config.get("artifacts", {})
            
            # Use environment variables or config defaults
            import os
            storage_provider = (
                artifacts_config.get("storage_provider") or
                os.getenv("ARTIFACT_STORAGE_PROVIDER", "filesystem")
            )
            session_provider = (
                artifacts_config.get("session_provider") or
                os.getenv("ARTIFACT_SESSION_PROVIDER", "memory")
            )
            bucket = (
                artifacts_config.get("bucket") or
                os.getenv("ARTIFACT_BUCKET", f"mcp-{self.server_name}")
            )
            
            # Set up filesystem root if using filesystem storage
            if storage_provider == "filesystem":
                fs_root = (
                    artifacts_config.get("filesystem_root") or
                    os.getenv("ARTIFACT_FS_ROOT") or
                    os.path.expanduser(f"~/.chuk_mcp_artifacts/{self.server_name}")
                )
                os.environ["ARTIFACT_FS_ROOT"] = fs_root
            
            # Create artifact store
            self.artifact_store = ArtifactStore(
                storage_provider=storage_provider,
                session_provider=session_provider,
                bucket=bucket
            )
            
            # Validate configuration
            config_status = await self.artifact_store.validate_configuration()
            if (config_status["session"]["status"] == "ok" and 
                config_status["storage"]["status"] == "ok"):
                self.logger.info(
                    f"Artifact store initialized: {storage_provider}/{session_provider} -> {bucket}"
                )
            else:
                self.logger.warning(f"Artifact store configuration issues: {config_status}")
                
        except Exception as e:
            self.logger.error(f"Failed to setup artifact store: {e}")
            self.artifact_store = None
    
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
    
    async def _inject_session_context(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inject session context into tool arguments if needed.
        
        Args:
            tool_name: Name of the tool being called
            arguments: Current tool arguments
            
        Returns:
            Updated arguments with session context if applicable
        """
        # Enhanced list of tools that require session context
        session_required_tools = [
            'write_file', 'upload_file', 'list_session_files', 'list_directory',
            'read_file', 'delete_file', 'copy_file', 'move_file',
            'get_file_metadata', 'get_presigned_url', 'get_storage_stats'
        ]
        
        # Check if this tool needs session context and doesn't have session_id
        needs_session = any(pattern in tool_name for pattern in session_required_tools)
        
        if needs_session and 'session_id' not in arguments:
            # If no current session, create one automatically
            if not self.current_session:
                import uuid
                import time
                # Generate a session ID for this connection
                timestamp = int(time.time())
                session_suffix = str(uuid.uuid4().hex)[:8]
                self.current_session = f"mcp-session-{timestamp}-{session_suffix}"
                self.logger.info(f"Auto-created session for MCP client: {self.current_session}")
            
            # Inject the session ID
            arguments = arguments.copy()  # Don't modify original
            arguments['session_id'] = self.current_session
            self.logger.debug(f"Injected session_id '{self.current_session}' into {tool_name}")
        
        return arguments

    async def serve(self, custom_handlers: Optional[Dict[str, Callable]] = None) -> None:
        """
        Run the MCP server with stdio communication.
        
        Sets up server, tool listing, and tool execution handlers with session support
        and enhanced artifact store integration.
        
        Args:
            custom_handlers: Optional dictionary of custom handlers to add to the server.
        """
        try:
            # Setup artifact store if available
            await self._setup_artifact_store()
            
            # Ensure tools registry is initialized and we're using the right one
            if not self.tools_registry:
                self.logger.warning("No tools registry available - importing from global")
                self.tools_registry = await self._import_tools_registry()
            else:
                self.logger.info(f"Using existing tools registry with {len(self.tools_registry)} tools")
                # Log some example tool names for debugging
                if self.tools_registry:
                    tool_names = list(self.tools_registry.keys())[:5]  # First 5 tools
                    self.logger.debug(f"Sample tools: {', '.join(tool_names)}")
            
            # CRITICAL: Initialize any tool placeholders BEFORE creating server handlers
            self.logger.info("Initializing tool metadata...")
            await initialize_tool_registry()
            
            # Verify tools have metadata after initialization
            tools_with_metadata = sum(1 for func in self.tools_registry.values() if hasattr(func, '_mcp_tool'))
            self.logger.info(f"Tools with metadata after initialization: {tools_with_metadata}/{len(self.tools_registry)}")
            
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
                try:
                    self.logger.info(f"list_tools called - registry has {len(self.tools_registry)} tools")
                    
                    if not self.tools_registry:
                        self.logger.warning("No tools available in registry")
                        return []
                    
                    # Debug: Show all tool names
                    all_tool_names = list(self.tools_registry.keys())
                    self.logger.debug(f"All registered tools: {', '.join(all_tool_names)}")
                    
                    # Check which tools have _mcp_tool metadata
                    tools_with_metadata = []
                    tools_without_metadata = []
                    
                    self.logger.debug("Checking tools for metadata...")
                    
                    for name, func in self.tools_registry.items():
                        try:
                            if hasattr(func, '_mcp_tool'):
                                tools_with_metadata.append(name)
                                self.logger.debug(f"Tool {name} has metadata")
                            else:
                                tools_without_metadata.append(name)
                                self.logger.debug(f"Tool {name} missing metadata")
                        except Exception as e:
                            self.logger.error(f"Error checking tool {name}: {e}")
                            tools_without_metadata.append(name)
                    
                    self.logger.info(f"Tools with metadata: {len(tools_with_metadata)}")
                    self.logger.info(f"Tools without metadata: {len(tools_without_metadata)}")
                    
                    if tools_without_metadata:
                        self.logger.warning(f"Tools missing _mcp_tool metadata: {', '.join(tools_without_metadata[:5])}")
                    
                    self.logger.debug("Building tools list...")
                    
                    tools_list = []
                    for func in self.tools_registry.values():
                        try:
                            if hasattr(func, '_mcp_tool'):
                                tools_list.append(func._mcp_tool)
                                self.logger.debug(f"Added tool to list: {func._mcp_tool.name}")
                            else:
                                self.logger.debug(f"Skipped tool without metadata")
                        except Exception as e:
                            self.logger.error(f"Error adding tool to list: {e}")
                    
                    # Log tool summary for debugging
                    tool_count = len(tools_list)
                    artifact_tools = len([t for t in tools_list if any(kw in t.name for kw in ['file', 'upload', 'write', 'read', 'list'])])
                    
                    self.logger.info(f"Returning {tool_count} tools ({artifact_tools} artifact-related)")
                    
                    return tools_list
                    
                except Exception as e:
                    self.logger.error(f"Error in list_tools: {e}", exc_info=True)
                    return []

            @server.call_tool()
            async def call_tool(
                name: str,
                arguments: Dict[str, Any]
            ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
                """
                Execute a tool with session context support and enhanced error handling.

                Enhanced with session management, improved tool resolution, and artifact store integration.
                """
                try:
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
                        available_tools = ", ".join(sorted(registry.keys())[:10])  # Show first 10 for debugging
                        raise ValueError(
                            f"Tool not found: {name}. Available tools: {available_tools}..."
                        )

                    func = registry[resolved]
                    
                    # Enhanced: Inject session context for tools that need it
                    enhanced_arguments = await self._inject_session_context(resolved, arguments)
                    
                    self.logger.debug("Executing '%s' with %s", resolved, enhanced_arguments)
                    
                    # Track if this is an artifact-related operation
                    is_artifact_tool = any(kw in resolved for kw in ['file', 'upload', 'write', 'read', 'list', 'delete', 'copy', 'move'])
                    
                    try:
                        # Set session context if available
                        if self.current_session:
                            set_session_context(self.current_session)
                        
                        result = await func(**enhanced_arguments)
                        
                        # IMPORTANT: Update the server's session if the tool changed it
                        # This allows tools like set_session to persist their changes
                        current_context = get_session_context()
                        if current_context and current_context != self.current_session:
                            self.current_session = current_context
                            if is_artifact_tool:
                                self.logger.debug(f"Session context updated to: {current_context}")
                        
                    except Exception as exc:
                        error_msg = str(exc)
                        
                        # Enhanced error reporting for artifact tools
                        if is_artifact_tool and self.artifact_store is None:
                            error_msg = f"Artifact store not available: {error_msg}"
                        elif "session" in error_msg.lower() and not self.current_session:
                            error_msg = f"No session context available. {error_msg}"
                        
                        self.logger.error("Tool '%s' failed: %s", resolved, error_msg, exc_info=True)
                        raise ValueError(f"Error processing tool '{resolved}': {error_msg}") from exc
                    finally:
                        # DON'T clear session context - let it persist between calls
                        # The session context should maintain state across tool executions
                        pass

                    # ---------- normalise result to MCP content ----------
                    if (
                        isinstance(result, list)
                        and all(isinstance(r, (TextContent, ImageContent, EmbeddedResource)) for r in result)
                    ):
                        return result

                    if isinstance(result, str):
                        return [TextContent(type="text", text=result)]

                    return [TextContent(type="text", text=json.dumps(result, indent=2))]
                    
                except Exception as e:
                    self.logger.error(f"Error in call_tool: {e}", exc_info=True)
                    raise
            
            # Add any custom handlers
            if custom_handlers:
                for handler_name, handler_func in custom_handlers.items():
                    self.logger.debug(f"Adding custom handler: {handler_name}")
                    setattr(server, handler_name, handler_func)

            options = server.create_initialization_options()
            server_type = self.config.get("server", {}).get("type", "stdio")
            
            if server_type == "stdio":
                self.logger.info("Starting stdio server with session support and artifact store")
                async with stdio_server() as (read_stream, write_stream):
                    await server.run(read_stream, write_stream, options)
            elif server_type == "sse":
                self.logger.info("Starting MCP server over SSE with session support and artifact store")
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
                
                config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
                uvicorn_server = uvicorn.Server(config)
                await uvicorn_server.serve()
            else:
                raise ValueError(f"Unknown server type: {server_type}")
                
        except Exception as e:
            self.logger.error(f"Error in serve method: {e}", exc_info=True)
            raise
        """
        Run the MCP server with stdio communication.
        
        Sets up server, tool listing, and tool execution handlers with session support
        and enhanced artifact store integration.
        
        Args:
            custom_handlers: Optional dictionary of custom handlers to add to the server.
        """
        # Setup artifact store if available
        await self._setup_artifact_store()
        
        # Ensure tools registry is initialized and we're using the right one
        if not self.tools_registry:
            self.logger.warning("No tools registry available - importing from global")
            self.tools_registry = await self._import_tools_registry()
        else:
            self.logger.info(f"Using existing tools registry with {len(self.tools_registry)} tools")
            # Log some example tool names for debugging
            if self.tools_registry:
                tool_names = list(self.tools_registry.keys())[:5]  # First 5 tools
                self.logger.debug(f"Sample tools: {', '.join(tool_names)}")
        
        # CRITICAL: Initialize any tool placeholders BEFORE creating server handlers
        self.logger.info("Initializing tool metadata...")
        await initialize_tool_registry()
        
        # Verify tools have metadata after initialization
        tools_with_metadata = sum(1 for func in self.tools_registry.values() if hasattr(func, '_mcp_tool'))
        self.logger.info(f"Tools with metadata after initialization: {tools_with_metadata}/{len(self.tools_registry)}")
        
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
            try:
                self.logger.info(f"list_tools called - registry has {len(self.tools_registry)} tools")
                
                if not self.tools_registry:
                    self.logger.warning("No tools available in registry")
                    return []
                
                # Debug: Show all tool names
                all_tool_names = list(self.tools_registry.keys())
                self.logger.debug(f"All registered tools: {', '.join(all_tool_names)}")
                
                # Check which tools have _mcp_tool metadata
                tools_with_metadata = []
                tools_without_metadata = []
                
                self.logger.debug("Checking tools for metadata...")
                
                for name, func in self.tools_registry.items():
                    try:
                        if hasattr(func, '_mcp_tool'):
                            tools_with_metadata.append(name)
                            self.logger.debug(f"Tool {name} has metadata")
                        else:
                            tools_without_metadata.append(name)
                            self.logger.debug(f"Tool {name} missing metadata")
                    except Exception as e:
                        self.logger.error(f"Error checking tool {name}: {e}")
                        tools_without_metadata.append(name)
                
                self.logger.info(f"Tools with metadata: {len(tools_with_metadata)}")
                self.logger.info(f"Tools without metadata: {len(tools_without_metadata)}")
                
                if tools_without_metadata:
                    self.logger.warning(f"Tools missing _mcp_tool metadata: {', '.join(tools_without_metadata[:5])}")
                
                self.logger.debug("Building tools list...")
                
                tools_list = []
                for func in self.tools_registry.values():
                    try:
                        if hasattr(func, '_mcp_tool'):
                            tools_list.append(func._mcp_tool)
                            self.logger.debug(f"Added tool to list: {func._mcp_tool.name}")
                        else:
                            self.logger.debug(f"Skipped tool without metadata")
                    except Exception as e:
                        self.logger.error(f"Error adding tool to list: {e}")
                
                # Log tool summary for debugging
                tool_count = len(tools_list)
                artifact_tools = len([t for t in tools_list if any(kw in t.name for kw in ['file', 'upload', 'write', 'read', 'list'])])
                
                self.logger.info(f"Returning {tool_count} tools ({artifact_tools} artifact-related)")
                
                return tools_list
                
            except Exception as e:
                self.logger.error(f"Error in list_tools: {e}", exc_info=True)
                return []

        @server.call_tool()
        async def call_tool(
            name: str,
            arguments: Dict[str, Any]
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            """
            Execute a tool with session context support and enhanced error handling.

            Enhanced with session management, improved tool resolution, and artifact store integration.
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
                available_tools = ", ".join(sorted(registry.keys())[:10])  # Show first 10 for debugging
                raise ValueError(
                    f"Tool not found: {name}. Available tools: {available_tools}..."
                )

            func = registry[resolved]
            
            # Enhanced: Inject session context for tools that need it
            enhanced_arguments = await self._inject_session_context(resolved, arguments)
            
            self.logger.debug("Executing '%s' with %s", resolved, enhanced_arguments)
            
            # Track if this is an artifact-related operation
            is_artifact_tool = any(kw in resolved for kw in ['file', 'upload', 'write', 'read', 'list', 'delete', 'copy', 'move'])
            
            try:
                # Set session context if available
                if self.current_session:
                    set_session_context(self.current_session)
                
                result = await func(**enhanced_arguments)
                
                # IMPORTANT: Update the server's session if the tool changed it
                # This allows tools like set_session to persist their changes
                current_context = get_session_context()
                if current_context and current_context != self.current_session:
                    self.current_session = current_context
                    if is_artifact_tool:
                        self.logger.debug(f"Session context updated to: {current_context}")
                
            except Exception as exc:
                error_msg = str(exc)
                
                # Enhanced error reporting for artifact tools
                if is_artifact_tool and self.artifact_store is None:
                    error_msg = f"Artifact store not available: {error_msg}"
                elif "session" in error_msg.lower() and not self.current_session:
                    error_msg = f"No session context available. {error_msg}"
                
                self.logger.error("Tool '%s' failed: %s", resolved, error_msg, exc_info=True)
                raise ValueError(f"Error processing tool '{resolved}': {error_msg}") from exc
            finally:
                # DON'T clear session context - let it persist between calls
                # The session context should maintain state across tool executions
                pass

            # ---------- normalise result to MCP content ----------
            if (
                isinstance(result, list)
                and all(isinstance(r, (TextContent, ImageContent, EmbeddedResource)) for r in result)
            ):
                return result

            if isinstance(result, str):
                return [TextContent(type="text", text=result)]

            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # Add any custom handlers
        if custom_handlers:
            for handler_name, handler_func in custom_handlers.items():
                self.logger.debug(f"Adding custom handler: {handler_name}")
                setattr(server, handler_name, handler_func)

        options = server.create_initialization_options()
        server_type = self.config.get("server", {}).get("type", "stdio")
        
        if server_type == "stdio":
            self.logger.info("Starting stdio server with session support and artifact store")
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, options)
        elif server_type == "sse":
            self.logger.info("Starting MCP server over SSE with session support and artifact store")
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
    
    def set_session(self, session_id: str) -> None:
        """
        Set the current session for this server instance.
        
        Args:
            session_id: Session identifier
        """
        self.current_session = session_id
        set_session_context(session_id)
        self.logger.info(f"Server session set to: {session_id}")
    
    def get_current_session(self) -> Optional[str]:
        """
        Get the current session ID.
        
        Returns:
            Current session ID or None
        """
        return self.current_session
    
    def get_artifact_store(self) -> Optional[ArtifactStore]:
        """
        Get the artifact store instance.
        
        Returns:
            ArtifactStore instance or None if not available
        """
        return self.artifact_store
    
    async def close(self) -> None:
        """Clean up server resources."""
        if self.artifact_store:
            try:
                await self.artifact_store.close()
            except Exception as e:
                self.logger.warning(f"Error closing artifact store: {e}")