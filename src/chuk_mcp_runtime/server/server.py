# chuk_mcp_runtime/server/server.py
"""
CHUK MCP Server

Core MCP server with

* automatic session-ID injection for artifact tools
* optional bearer-token auth middleware
* transparent chuk_artifacts integration
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import time
import uuid
from inspect import iscoroutinefunction
from typing import Any, Callable, Dict, List, Optional, Union

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from chuk_mcp_runtime.common.mcp_tool_decorator import (
    TOOLS_REGISTRY,
    initialize_tool_registry,
)
from chuk_mcp_runtime.common.tool_naming import resolve_tool_name, update_naming_maps
from chuk_mcp_runtime.common.verify_credentials import validate_token
from chuk_mcp_runtime.server.logging_config import get_logger
from chuk_mcp_runtime.session.session_management import (
    SessionError,
    clear_session_context,
    get_session_context,
    set_session_context,
)

# ─────────────────────────── Optional chuk_artifacts ──────────────────────────
try:
    from chuk_artifacts import ArtifactStore

    CHUK_ARTIFACTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    CHUK_ARTIFACTS_AVAILABLE = False
    ArtifactStore = None  # type: ignore

# ------------------------------------------------------------------------------
# Authentication middleware
# ------------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """Simple bearer-token / cookie-based auth."""

    def __init__(self, app: ASGIApp, auth: Optional[str] = None) -> None:
        super().__init__(app)
        self.auth = auth

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        if self.auth != "bearer":
            return await call_next(request)

        token = None
        # 1) Authorization header
        if "Authorization" in request.headers:
            m = re.match(r"Bearer\s+(.+)", request.headers["Authorization"], re.I)
            if m:
                token = m.group(1)
        # 2) cookie fallback
        if not token:
            token = request.cookies.get("jwt_token")

        if not token:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        try:
            payload = await validate_token(token)
            request.scope["user"] = payload
        except HTTPException as exc:
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

        return await call_next(request)


# ------------------------------------------------------------------------------
# MCPServer
# ------------------------------------------------------------------------------


class MCPServer:
    """Central MCP server with session & artifact-store support."""

    # ------------------------------------------------------------------ #
    # Construction & helpers                                             #
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        config: Dict[str, Any],
        tools_registry: Optional[Dict[str, Callable]] = None,
    ) -> None:
        self.config = config
        self.logger = get_logger("chuk_mcp_runtime.server", config)

        self.server_name = config.get("host", {}).get("name", "generic-mcp")
        self.tools_registry = tools_registry or TOOLS_REGISTRY
        self.current_session: Optional[str] = None
        self.artifact_store: Optional[ArtifactStore] = None

        update_naming_maps()  # make sure resolve_tool_name works

    async def _setup_artifact_store(self) -> None:
        if not CHUK_ARTIFACTS_AVAILABLE:
            self.logger.info("chuk_artifacts not installed – file tools disabled")
            return

        cfg = self.config.get("artifacts", {})
        storage = cfg.get("storage_provider", os.getenv("ARTIFACT_STORAGE_PROVIDER", "filesystem"))
        session = cfg.get("session_provider", os.getenv("ARTIFACT_SESSION_PROVIDER", "memory"))
        bucket = cfg.get("bucket", os.getenv("ARTIFACT_BUCKET", f"mcp-{self.server_name}"))

        # filesystem root (only when storage == filesystem)
        if storage == "filesystem":
            fs_root = cfg.get("filesystem_root", os.getenv("ARTIFACT_FS_ROOT",
                                                           os.path.expanduser(f"~/.chuk_mcp_artifacts/{self.server_name}")))
            os.environ["ARTIFACT_FS_ROOT"] = fs_root  # chuk_artifacts respects this

        try:
            self.artifact_store = ArtifactStore(storage_provider=storage,
                                                session_provider=session,
                                                bucket=bucket)
            status = await self.artifact_store.validate_configuration()
            if status["session"]["status"] == "ok" and status["storage"]["status"] == "ok":
                self.logger.info(
                    "Artifact store ready: %s/%s → %s", storage, session, bucket
                )
            else:
                self.logger.warning("Artifact-store config issues: %s", status)
        except Exception as exc:  # pragma: no cover
            self.logger.error("Artifact-store init failed: %s", exc)
            self.artifact_store = None

    async def _import_tools_registry(self) -> Dict[str, Callable]:
        mod = self.config.get("tools", {}).get("registry_module",
                                               "chuk_mcp_runtime.common.mcp_tool_decorator")
        attr = self.config.get("tools", {}).get("registry_attr", "TOOLS_REGISTRY")

        try:
            m = importlib.import_module(mod)
            if iscoroutinefunction(getattr(m, "initialize_tool_registry", None)):
                await m.initialize_tool_registry()
            registry: Dict[str, Callable] = getattr(m, attr, {})
        except Exception as exc:
            self.logger.error("Unable to import tool registry: %s", exc)
            registry = {}

        update_naming_maps()
        return registry

    # ------------------------------------------------------------------ #
    # Session helpers                                                    #
    # ------------------------------------------------------------------ #

    async def _inject_session_context(
        self, tool_name: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Auto-add `session_id` for artifact tools when caller omitted it."""
        NEEDS_SESSION = (
            "file",
            "upload",
            "write",
            "read",
            "list",
            "delete",
            "copy",
            "move",
            "metadata",
            "presigned",
            "stats",
        )
        if any(p in tool_name for p in NEEDS_SESSION) and "session_id" not in args:
            if not self.current_session:
                self.current_session = (
                    f"mcp-session-{int(time.time())}-{uuid.uuid4().hex[:8]}"
                )
                self.logger.info("Auto-created session: %s", self.current_session)
            args = args.copy()
            args["session_id"] = self.current_session
        return args

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    async def serve(self, custom_handlers: Optional[Dict[str, Callable]] = None) -> None:
        """Boot the MCP server (stdio or SSE) and serve forever."""
        await self._setup_artifact_store()

        if not self.tools_registry:
            self.tools_registry = await self._import_tools_registry()

        await initialize_tool_registry()  # make sure decorators ran
        update_naming_maps()

        server = Server(self.server_name)

        # ----------------------------- list_tools ----------------------------- #

        @server.list_tools()
        async def list_tools() -> List[Tool]:
            self.logger.info("list_tools called – %d tools total", len(self.tools_registry))
            return [
                func._mcp_tool
                for func in self.tools_registry.values()
                if hasattr(func, "_mcp_tool")
            ]

        # ----------------------------- call_tool ----------------------------- #

        @server.call_tool()
        async def call_tool(
            name: str, arguments: Dict[str, Any]
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:

            registry = self.tools_registry

            # 1) direct or resolved lookup
            resolved = name if name in registry else resolve_tool_name(name)
            if resolved not in registry:
                matches = [k for k in registry if k.endswith(f"_{name}") or k.endswith(f".{name}")]
                if len(matches) == 1:
                    resolved = matches[0]
            if resolved not in registry:
                raise ValueError(f"Tool not found: {name}")

            func = registry[resolved]
            arguments = await self._inject_session_context(resolved, arguments)

            # Execute ---------------------------------------------------------
            try:
                if self.current_session:
                    set_session_context(self.current_session)

                result = await func(**arguments)

                # if tool set/changed the session itself
                new_ctx = get_session_context()
                if new_ctx and new_ctx != self.current_session:
                    self.current_session = new_ctx

            except Exception as exc:
                self.logger.error("Tool '%s' failed: %s", resolved, exc, exc_info=True)
                raise

            # Wrap artifact result with session_id ---------------------------
            result = {
                "session_id": self.current_session,
                "content": result,
                "isError": False,
            }

            # Normalise to MCP content ---------------------------------------
            if (
                isinstance(result, list)
                and all(isinstance(r, (TextContent, ImageContent, EmbeddedResource)) for r in result)
            ):
                return result

            if isinstance(result, str):
                return [TextContent(type="text", text=result)]

            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # custom proxy / etc. handlers ---------------------------------------
        if custom_handlers:
            for k, v in custom_handlers.items():
                setattr(server, k, v)

        # transport ----------------------------------------------------------
        opts = server.create_initialization_options()
        mode = self.config.get("server", {}).get("type", "stdio")

        if mode == "stdio":
            self.logger.info("Starting MCP (stdio) …")
            async with stdio_server() as (r, w):
                await server.run(r, w, opts)

        elif mode == "sse":
            cfg = self.config.get("sse", {})
            host, port = cfg.get("host", "0.0.0.0"), cfg.get("port", 8000)
            sse_path, msg_path = cfg.get("sse_path", "/sse"), cfg.get("message_path", "/messages/")
            transport = SseServerTransport(msg_path)

            async def _handle_sse(request: Request):
                async with transport.connect_sse(request.scope, request.receive, request._send) as streams:
                    await server.run(streams[0], streams[1], opts)
                return Response()

            app = Starlette(
                routes=[
                    Route(sse_path, _handle_sse, methods=["GET"]),
                    Mount(msg_path, app=transport.handle_post_message),
                ],
                middleware=[Middleware(AuthMiddleware, auth=self.config.get("server", {}).get("auth"))],
            )
            self.logger.info("Starting MCP (SSE) on %s:%s …", host, port)
            await uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info")).serve()
        else:
            raise ValueError(f"Unknown server type: {mode}")

    # ------------------------------------------------------------------ #
    # Misc administrative helpers                                        #
    # ------------------------------------------------------------------ #

    async def register_tool(self, name: str, func: Callable) -> None:
        if not hasattr(func, "_mcp_tool"):
            self.logger.warning("Function %s lacks _mcp_tool metadata", func.__name__)
            return
        self.tools_registry[name] = func
        update_naming_maps()

    async def get_tool_names(self) -> List[str]:
        return list(self.tools_registry)

    # session getters / setters -----------------------------------------

    def set_session(self, session_id: str) -> None:
        self.current_session = session_id
        set_session_context(session_id)

    def get_current_session(self) -> Optional[str]:
        return self.current_session

    def get_artifact_store(self) -> Optional[ArtifactStore]:
        return self.artifact_store

    async def close(self) -> None:
        if self.artifact_store:
            try:
                await self.artifact_store.close()
            except Exception as exc:  # pragma: no cover
                self.logger.warning("Error closing artifact store: %s", exc)
