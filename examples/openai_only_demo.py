# chuk_mcp_runtime/proxy/manager.py
"""
chuk_mcp_runtime.proxy.manager
==============================

Expose each remote MCP tool exactly once under

    proxy.<server>.<tool>

Supports **stdio** (local process) **and** **SSE** (remote HTTP stream)
transports as declared in *proxy_config.yaml*.

Configuration extras
--------------------
proxy:
  enabled: true
  namespace: proxy
  keep_root_aliases: false   # ← if *true* the single-dot aliases
                             #    proxy.<tool> are kept instead of pruned
  openai_compatible: true    # ← if *true* register underscore aliases
  only_openai_tools: false   # ← if *true* keep ONLY underscore aliases
"""

from __future__ import annotations

import json, os, tempfile, logging
from typing import Any, Dict, Callable

from chuk_mcp_runtime.common.errors import ServerError
from chuk_mcp_runtime.proxy.tool_wrapper import create_proxy_tool
from chuk_mcp_runtime.server.logging_config import get_logger
from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY, mcp_tool

try:
    from chuk_tool_processor.mcp import setup_mcp_stdio, setup_mcp_sse
    from chuk_tool_processor.registry import ToolRegistryProvider
    from chuk_tool_processor.models.tool_call import ToolCall
except ImportError:                                             # stubs for type-checking
    class ToolRegistryProvider:                                 # type: ignore
        @staticmethod
        def get_registry(): return {}
    class ToolCall:                                             # type: ignore
        def __init__(self, **kwargs): pass

logger = get_logger("chuk_mcp_runtime.proxy")


# ──────────────────────────  helpers  ──────────────────────────
def to_openai_compatible_name(name: str) -> str:
    """proxy.foo.bar  →  proxy_foo_bar"""
    return name.replace(".", "_")


# ─────────────────────  main manager class  ────────────────────
class ProxyServerManager:
    """Boot side-car MCP servers and expose their tools locally."""

    # ─────────────────── construction / teardown ───────────────────
    def __init__(self, config: Dict[str, Any], project_root: str):
        pxy = config.get("proxy", {})
        self.enabled            = pxy.get("enabled", False)
        self.default_namespace  = pxy.get("namespace", "proxy")
        self.keep_root_aliases  = pxy.get("keep_root_aliases", False)
        self.openai_compatible  = pxy.get("openai_compatible", False)
        self.only_openai_tools  = pxy.get("only_openai_tools", False)
        self.project_root       = project_root
        self.mcp_servers        = config.get("mcp_servers", {})

        if self.only_openai_tools and not self.openai_compatible:
            self.only_openai_tools = False                      # guard-rail

        logger.setLevel(logging.DEBUG)
        logger.debug("ProxyServerManager init: openai_compatible=%s | only_openai_tools=%s",
                     self.openai_compatible, self.only_openai_tools)

        self.tool_processor = self.stream_manager = None
        self.running_servers: Dict[str, Dict[str, Any]] = {}
        self._tmp_cfg: tempfile.NamedTemporaryFile | None = None

        self.openai_wrappers: Dict[str, Callable] = {}
        self.openai_to_original: Dict[str, str]   = {}

    # ──────────────────────── startup logic ────────────────────────
    async def start_servers(self) -> None:
        if not (self.enabled and self.mcp_servers):
            logger.info("Proxy disabled or no servers configured"); return

        stdio_cfg, stdio, stdio_map   = {"mcpServers": {}}, [], {}
        sse_servers, sse_map          = [], {}

        # build transport configs
        for name, opts in self.mcp_servers.items():
            if not opts.get("enabled", True): continue
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
                stdio_map[len(stdio_map)] = name
                stdio.append(name)
            else:
                sse_servers.append({"name": name,
                                    "url":  opts.get("url", ""),
                                    "api_key": opts.get("api_key", "")})
                sse_map[len(sse_map)] = name

        # launch transports
        try:
            if stdio:
                self._tmp_cfg = tempfile.NamedTemporaryFile(delete=False, mode="w")
                json.dump(stdio_cfg, self._tmp_cfg); self._tmp_cfg.flush()
                self.tool_processor, self.stream_manager = await setup_mcp_stdio(
                    config_file=self._tmp_cfg.name,
                    servers=stdio, server_names=stdio_map,
                    namespace=self.default_namespace,
                )
            elif sse_servers:
                self.tool_processor, self.stream_manager = await setup_mcp_sse(
                    servers=sse_servers, server_names=sse_map,
                    namespace=self.default_namespace,
                )
            else:
                logger.error("No enabled MCP servers declared"); return
        except Exception as exc:
            logger.error("Error starting transports: %s", exc, exc_info=True); raise

        for srv in (*stdio, *(s["name"] for s in sse_servers)):
            self.running_servers[srv] = {"wrappers": {}}

        await self._wrap_and_prune()

    async def stop_servers(self) -> None:
        if self.stream_manager: await self.stream_manager.close()
        if self._tmp_cfg:
            try: os.unlink(self._tmp_cfg.name)
            except OSError: pass
        self.running_servers.clear()
        self.tool_processor = self.stream_manager = self._tmp_cfg = None
        self.openai_wrappers.clear(); self.openai_to_original.clear()

    # ─────────────────────── wrapping helpers ───────────────────────
    @staticmethod
    def _del_nested(bucket: Dict, ns: str, name: str) -> None:
        sub = bucket.get(ns)
        if isinstance(sub, dict):
            sub.pop(name, None)
            if not sub: bucket.pop(ns, None)

    @staticmethod
    def _prune(reg, ns: str, name: str) -> None:
        """Delete *(ns, name)* entry from ToolRegistryProvider registry."""
        if hasattr(reg, "_tools"):
            ProxyServerManager._del_nested(reg._tools, ns, name)      # type: ignore[attr-defined]
        if hasattr(reg, "_metadata"):
            ProxyServerManager._del_nested(reg._metadata, ns, name)   # type: ignore[attr-defined]

    async def _create_openai_wrapper(self, dotted_fq: str, wrapper: Callable):
        openai_name = to_openai_compatible_name(dotted_fq)

        @mcp_tool(name=openai_name, description=wrapper._mcp_tool.description)  # type: ignore[arg-type]
        async def _wrapper(**kwargs):
            res = wrapper(**kwargs)
            if hasattr(res, "__await__"): res = await res
            return res

        self.openai_wrappers[openai_name]    = _wrapper
        self.openai_to_original[openai_name] = dotted_fq
        logger.debug("Created OpenAI wrapper: %s", openai_name)

    # ─────────────────────── core discovery ─────────────────────────
    async def _wrap_and_prune(self) -> None:
        if not self.stream_manager: return

        registry    = ToolRegistryProvider.get_registry()
        keep_prefix = f"{self.default_namespace}."

        # 1) wrap
        for server in self.running_servers:
            try:
                tools = await self.stream_manager.list_tools(server)
            except Exception as exc:
                logger.error("list_tools failed for %s: %s", server, exc); continue

            for meta in tools:
                name = meta.get("name");  # remote tool name
                if not name: continue
                ns   = f"{keep_prefix}{server}"
                fq   = f"{ns}.{name}"

                wrapper = create_proxy_tool(ns, name, self.stream_manager, meta)
                if not (self.openai_compatible and self.only_openai_tools):
                    self.running_servers[server]["wrappers"][name] = wrapper
                if self.openai_compatible:
                    await self._create_openai_wrapper(fq, wrapper)

        # 2) prune unwanted aliases
        for ns, name in list(registry.list_tools()):
            full = f"{ns}.{name}" if ns else name
            prune_dot   = self.openai_compatible and self.only_openai_tools and "." in full
            prune_alias = (not self.keep_root_aliases
                           and "." in full
                           and not full.startswith(keep_prefix))
            if prune_dot or prune_alias:
                type(self)._prune(registry, ns, name)

    # ─────────────────────── utility APIs ───────────────────────────
    async def process_text(self, text: str):
        if not self.tool_processor: raise ServerError("Proxy not running")
        return await self.tool_processor.process_text(text)

    async def proxy_tool_call(self, ns: str, tool: str, args: Dict[str, Any]):
        if not self.tool_processor: raise ServerError("Proxy not running")
        call = ToolCall(tool=f"{ns}.{tool}", arguments=args)
        for fn in ("run_tool_calls","run_calls","process_tool_calls",
                   "execute_calls","process_calls"):
            if hasattr(self.tool_processor, fn):
                res = await getattr(self.tool_processor, fn)([call]); break
        else:
            raise ServerError("ToolProcessor lacks compatible call method")
        first = res[0]
        if getattr(first, "error", None): raise ServerError(first.error)
        return first.result

    def get_all_tools(self) -> Dict[str, Callable]:
        """Return mapping tool-name → wrapper for everything we expose."""
        out: Dict[str, Callable] = {}

        for srv, info in self.running_servers.items():
            for name, fn in info.get("wrappers", {}).items():
                dotted = f"{self.default_namespace}.{srv}.{name}"
                if not (self.openai_compatible and self.only_openai_tools):
                    out[dotted] = fn
                if self.openai_compatible:
                    underscore = to_openai_compatible_name(dotted)
                    if underscore in self.openai_wrappers:
                        out[underscore] = self.openai_wrappers[underscore]

        if self.openai_compatible and self.only_openai_tools and not out:
            for n, f in TOOLS_REGISTRY.items():
                if "_" in n and "." not in n:
                    out[n] = f

        logger.debug("Total tools exposed: %d", len(out))
        return out
