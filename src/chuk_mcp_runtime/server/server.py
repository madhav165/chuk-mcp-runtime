# server.py
# -*- coding: utf-8 -*-
"""
CHUK MCP Server
===============

Core runtime for discovering tools and exposing them over MCP.  
Supports both built-in transports supplied by *mcp*:

* **STDIO** – great for CLI tools and editor integrations.
* **SSE**   – HTTP streaming via Starlette + Uvicorn.

Select the transport in *config["server"]["type"]* (“stdio” | “sse”).
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
from mcp.server.sse import sse_server                 # requires starlette + uvicorn
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

# ── Local runtime ────────────────────────────────────────────────────
from chuk_mcp_runtime.server.logging_config import get_logger


class MCPServer:
    """
    Manage tool discovery/registration and run the MCP server over the chosen
    transport (stdio | sse).
    """

    # ------------------------------------------------------------------ #
    # Construction                                                       #
    # ------------------------------------------------------------------ #
    def __init__(
        self,
        config: Dict[str, Any],
        tools_registry: Optional[Dict[str, Callable]] = None,
    ):
        self.config = config
        self.logger = get_logger("chuk_mcp_runtime.server", config)
        self.server_name = config.get("host", {}).get("name", "generic-mcp")
        self.tools_registry = tools_registry or self._import_tools_registry()

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
            async with sse_server(self.config) as (r, w):
                await server.run(r, w, options)

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
