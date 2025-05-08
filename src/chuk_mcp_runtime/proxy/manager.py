# chuk-mcp-runtime/proxy/manager.py
"""
chuk_mcp_runtime.proxy.manager
==============================

Expose each remote MCP tool exactly once under

    proxy.<server>.<tool>

Supports **stdio** (local process) **and** **SSE** (remote HTTP stream)
transports as declared in *proxy_config.yaml*.
"""

from __future__ import annotations

import json, os, tempfile
from typing import Any, Dict

from chuk_mcp_runtime.common.errors import ServerError
from chuk_mcp_runtime.proxy.tool_wrapper import create_proxy_tool
from chuk_mcp_runtime.server.logging_config import get_logger

from chuk_tool_processor.mcp import (
    setup_mcp_stdio,
    setup_mcp_sse,
)
from chuk_tool_processor.registry import ToolRegistryProvider
from chuk_tool_processor.models.tool_call import ToolCall

logger = get_logger("chuk_mcp_runtime.proxy")


class ProxyServerManager:
    # ───────────────────── construction / teardown ──────────────────────
    def __init__(self, config: Dict[str, Any], project_root: str):
        pxy = config.get("proxy", {})

        self.enabled            = pxy.get("enabled", False)
        self.default_namespace  = pxy.get("namespace", "proxy")
        self.project_root       = project_root
        self.mcp_servers        = config.get("mcp_servers", {})

        self.tool_processor = self.stream_manager = None
        self.running_servers: Dict[str, Dict[str, Any]] = {}
        self._tmp_cfg: tempfile.NamedTemporaryFile | None = None

    async def start_servers(self) -> None:
        if not (self.enabled and self.mcp_servers):
            logger.info("Proxy disabled or no servers configured"); return

        stdio_cfg, stdio, stdio_map = {"mcpServers": {}}, [], {}
        sse_servers, sse_map = [], {}

        # ---- classify + build configs ----------------------------------
        for idx, (name, opts) in enumerate(self.mcp_servers.items()):
            if not opts.get("enabled", True):
                continue
            typ = opts.get("type", "stdio")

            if typ == "stdio":
                cwd = opts.get("location", "")
                if cwd and not os.path.isabs(cwd):
                    cwd = os.path.join(self.project_root, cwd)
                stdio_cfg["mcpServers"][name] = {
                    "command": opts.get("command", "python"),
                    "args":    opts.get("args", []),
                    "cwd":     cwd,
                }
                stdio.append(name); stdio_map[len(stdio_map)] = name
            elif typ == "sse":
                sse_servers.append({
                    "name": name,
                    "url":  opts.get("url", ""),
                    "api_key": opts.get("api_key", ""),
                })
                sse_map[len(sse_map)] = name
            else:
                logger.warning("Unsupported server type '%s' for %s", typ, name)

        if stdio:
            # write temp json for setup_mcp_stdio
            self._tmp_cfg = tempfile.NamedTemporaryFile(delete=False, mode="w")
            json.dump(stdio_cfg, self._tmp_cfg); self._tmp_cfg.flush()

            self.tool_processor, self.stream_manager = await setup_mcp_stdio(
                config_file=self._tmp_cfg.name,
                servers=stdio,
                server_names=stdio_map,
                namespace=self.default_namespace,
            )
        elif sse_servers:
            self.tool_processor, self.stream_manager = await setup_mcp_sse(
                servers=sse_servers,
                server_names=sse_map,
                namespace=self.default_namespace,
            )
        else:
            logger.error("No enabled MCP servers after filtering"); return

        # track running servers
        for name in (*stdio, *(d["name"] for d in sse_servers)):
            self.running_servers[name] = {"wrappers": {}}

        self._wrap_and_prune()

    async def stop_servers(self) -> None:
        if self.stream_manager:
            await self.stream_manager.close()
        if self._tmp_cfg:
            self._tmp_cfg.close(); os.unlink(self._tmp_cfg.name)

        self.running_servers.clear()
        self.tool_processor = self.stream_manager = self._tmp_cfg = None

    # ───────────────────────── helpers ────────────────────────────────
    @staticmethod
    def _del_nested(bucket: Dict, ns: str, name: str) -> None:
        sub = bucket.get(ns)
        if isinstance(sub, dict):
            sub.pop(name, None)
            if not sub: bucket.pop(ns, None)

    @staticmethod
    def _prune(reg, ns: str, name: str) -> None:
        if hasattr(reg, "_tools"):
            ProxyServerManager._del_nested(reg._tools, ns, name)       # type: ignore[attr-defined]
        if hasattr(reg, "_metadata"):
            ProxyServerManager._del_nested(reg._metadata, ns, name)    # type: ignore[attr-defined]

    # ───────────────────── wrap + prune logic ─────────────────────────
    def _wrap_and_prune(self) -> None:
        reg = ToolRegistryProvider.get_registry()
        keep_prefix = f"{self.default_namespace}."

        # 1) create wrappers
        for ns, name in list(reg.list_tools()):
            if ns != self.default_namespace:
                continue                                   # not a raw import
            server = self.stream_manager.get_server_for_tool(name)
            if not server:
                logger.warning("Cannot map raw tool '%s' to server", name); continue

            fq_ns = f"{keep_prefix}{server}"
            meta  = reg.get_metadata(name, self.default_namespace)
            wrapper = create_proxy_tool(fq_ns, name, self.stream_manager, meta)
            self.running_servers[server]["wrappers"][name] = wrapper
            logger.debug("Wrapped %s.%s", fq_ns, name)

        # 2) prune aliases (proxy.<tool> & default.proxy.<tool>)
        for ns, name in list(reg.list_tools()):
            if ns.startswith(keep_prefix):
                continue
            self._prune(reg, ns, name)
            logger.debug("Pruned alias %s.%s", ns, name)

    # ───────────────────── public helpers ─────────────────────────────
    async def process_text(self, text: str):
        if not self.tool_processor:
            raise ServerError("Proxy not running")
        return await self.tool_processor.process_text(text)

    async def proxy_tool_call(self, ns: str, tool: str, args: Dict[str, Any]):
        if not self.tool_processor:
            raise ServerError("Proxy not running")

        call = ToolCall(tool=f"{ns}.{tool}", arguments=args)
        for meth in (
            "run_tool_calls", "run_calls",
            "process_tool_calls", "execute_calls", "process_calls",
        ):
            if hasattr(self.tool_processor, meth):
                res = await getattr(self.tool_processor, meth)([call]); break
        else:
            raise ServerError("ToolProcessor lacks compatible call method")

        first = res[0]
        if getattr(first, "error", None):
            raise ServerError(first.error)
        return first.result

    def get_all_tools(self) -> Dict[str, Any]:
        """Map fully-qualified tool name → wrapper."""
        return {
            f"{self.default_namespace}.{srv}.{name}": fn
            for srv, inf in self.running_servers.items()
            for name, fn in inf["wrappers"].items()
        }
