# server.py
# -*- coding: utf-8 -*-
"""
CHUK MCP Server
===============

Core runtime for discovering tools and exposing them over MCP.  
Supports both built-in transports supplied by *mcp*:

* **STDIO** – great for CLI tools and editor integrations.
* **SSE**   – HTTP streaming via Starlette + Uvicorn.

Select the transport in *config["server"]["type"]* ("stdio" | "sse").
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
from typing import Any, Callable, Dict, List, Optional, Union

# ── MCP runtime imports ──────────────────────────────────────────────
from mcp.server import Server
from mcp.server.stdio import stdio_server            # always available
from mcp.server.sse import SseServerTransport        # requires starlette + uvicorn

# For SSE server
from starlette.applications import Starlette
from starlette.routing import Route, Mount
import uvicorn

from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

# ── Local runtime ────────────────────────────────────────────────────
from chuk_mcp_runtime.server.logging_config import get_logger


class MCPServer:
    """
    Manage tool discovery/registration and run the MCP server over the chosen
    transport (stdio | sse).
    """
    _endpoint: str
    # ------------------------------------------------------------------ #
    # Construction                                                       #
    # ------------------------------------------------------------------ #
    def __init__(
        self,
        config: Dict[str, Any],
        endpoint: str,
        tools_registry: Optional[Dict[str, Callable]] = None,
    ):
        self.config = config
        self.logger = get_logger("chuk_mcp_runtime.server", config)
        self.server_name = config.get("host", {}).get("name", "generic-mcp")
        self.tools_registry = tools_registry or self._import_tools_registry()
        self._endpoint = endpoint

    # ------------------------------------------------------------------ #
    # Tools discovery                                                    #
    # ------------------------------------------------------------------ #
    def _import_tools_registry(self) -> Dict[str, Callable]:
        tools_cfg = self.config.get("tools", {})
        module_path = tools_cfg.get(
            "registry_module", "chuk_mcp_runtime.common.mcp_tool_decorator"
        )
        attr_name = tools_cfg.get("registry_attr", "TOOLS_REGISTRY")

        try:
            mod = importlib.import_module(module_path)
            registry: Dict[str, Callable] = getattr(mod, attr_name, {})
        except (ImportError, AttributeError) as exc:
            self.logger.error("Failed to load TOOLS_REGISTRY from %s: %s", module_path, exc)
            registry = {}

        if registry:
            self.logger.debug(
                "Loaded %d tools: %s", len(registry), ", ".join(registry.keys())
            )
        else:
            self.logger.warning("No tools available")

        return registry

    # ------------------------------------------------------------------ #
    # Main entry                                                         #
    # ------------------------------------------------------------------ #
    async def serve(self, custom_handlers: Optional[Dict[str, Callable]] = None) -> None:
        import json
        
        server = Server(self.server_name)

        # ------------ list_tools --------------------------------------
        @server.list_tools()
        async def list_tools() -> List[Tool]:
            return [
                fn._mcp_tool  # type: ignore[attr-defined]
                for fn in self.tools_registry.values()
                if hasattr(fn, "_mcp_tool")
            ]

        # ------------ call_tool --------------------------------------
        @server.call_tool()
        async def call_tool(
            name: str, arguments: Dict[str, Any]
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            if name not in self.tools_registry:
                raise ValueError(f"Tool not found: {name}")

            func = self.tools_registry[name]
            self.logger.debug("Executing %s with %s", name, arguments)

            result = func(**arguments)
            if inspect.isawaitable(result):
                result = await result

            # Already content objects?
            if isinstance(result, list) and all(
                isinstance(x, (TextContent, ImageContent, EmbeddedResource)) for x in result
            ):
                return result

            # Plain string → wrap
            if isinstance(result, str):
                return [TextContent(type="text", text=result)]

            # Fallback → JSON dump
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # ------------ optional extra handlers ------------------------
        if custom_handlers:
            for name, fn in custom_handlers.items():
                self.logger.debug("Adding custom handler: %s", name)
                setattr(server, name, fn)

        options = server.create_initialization_options()
        srv_type = self.config.get("server", {}).get("type", "stdio").lower()

        # ------------------------------------------------------------------ #
        # Transport selection                                                #
        # ------------------------------------------------------------------ #
        if srv_type == "stdio":
            self.logger.info("Starting MCP server on STDIO")
            async with stdio_server() as (r, w):
                await server.run(r, w, options)

        elif srv_type == "sse":
            self.logger.info("Starting MCP server over SSE")
            # Get SSE server configuration
            sse_config = self.config.get("sse", {})
            host = sse_config.get("host", "127.0.0.1")
            port = sse_config.get("port", 8000)
            sse_path = sse_config.get("sse_path", "/sse")
            msg_path = sse_config.get("message_path", "/messages")
            
            # Create the starlette app with routes
            from starlette.applications import Starlette
            from starlette.responses import JSONResponse, PlainTextResponse, Response
            from starlette.routing import Route
            from starlette.requests import Request
            import json
            
            # Create the SSE transport instance
            sse_transport = SseServerTransport(msg_path)
            
            async def handle_sse(request: Request):
                async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
                    await server.run(streams[0], streams[1], options)
                # Return empty response to avoid NoneType error
                return Response()
            
            routes = [
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse_transport.handle_post_message),
            ]
            
            starlette_app = Starlette(routes=routes)
            
            # uvicorn.run(starlette_app, host="0.0.0.0", port=port)
            config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
            uvicorn_server = uvicorn.Server(config)
            await uvicorn_server.serve()
        else:
            raise ValueError(f"Unknown server type: {srv_type!r}")

    # ------------------------------------------------------------------ #
    # Helper utilities                                                   #
    # ------------------------------------------------------------------ #
    def register_tool(self, name: str, func: Callable) -> None:
        """Register a tool function at runtime (useful for tests)."""
        if not hasattr(func, "_mcp_tool"):
            self.logger.warning("Function %s lacks _mcp_tool metadata", func.__name__)
            return
        self.tools_registry[name] = func
        self.logger.debug("Registered tool: %s", name)

    def get_tool_names(self) -> List[str]:
        return list(self.tools_registry.keys())