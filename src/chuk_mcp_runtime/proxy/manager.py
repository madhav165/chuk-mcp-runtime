"""
chuk_mcp_runtime.proxy.manager
================================

Start/stop local or remote MCP side‑cars and expose their tools locally.
Each remote tool appears exactly **once**:

• dot wrapper :  ``proxy.<server>.<tool>``  (internal)
• underscore  :  ``<server>_<tool>``        (OpenAI‑style)

Flags in the YAML ``proxy`` section drive the behaviour:

```yaml
proxy:
  enabled: true            # turn the feature on/off
  namespace: proxy         # dot‑prefix for internal wrappers
  openai_compatible: true  # build underscore aliases
  keep_root_aliases: false # keep/destroy proxy.* aliases (when openai‑only)
  only_openai_tools: false # expose *only* underscore aliases
```
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Callable, Dict

from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY
from chuk_mcp_runtime.common.openai_compatibility import (
    create_openai_compatible_wrapper,
    to_openai_compatible_name,
)
from chuk_mcp_runtime.proxy.tool_wrapper import create_proxy_tool
from chuk_mcp_runtime.server.logging_config import get_logger

try:
    # Optional – only present if chuk‑tool‑processor is installed
    from chuk_tool_processor.mcp import setup_mcp_stdio
    from chuk_tool_processor.registry import ToolRegistryProvider
except ModuleNotFoundError:  # type‑checking stubs

    class ToolRegistryProvider:  # type: ignore
        @staticmethod
        def get_registry():
            class _Dummy:
                def list_tools(self):
                    return []

            return _Dummy()

logger = get_logger("chuk_mcp_runtime.proxy")

# ───────────────────────── helpers ──────────────────────────

def to_openai_name(dotted: str) -> str:
    """Historical helper (kept for backwards compatibility)."""
    return to_openai_compatible_name(dotted.replace("proxy.", "", 1))


# ───────────────────────── manager ──────────────────────────
class ProxyServerManager:
    """Boot the proxy layer and wire up tool wrappers."""

    # ─────────────── construction / teardown ────────────────
    def __init__(self, cfg: Dict[str, Any], project_root: str):
        pxy = cfg.get("proxy", {})
        self.enabled = pxy.get("enabled", False)
        self.ns_root = pxy.get("namespace", "proxy")
        self.keep_root_aliases = pxy.get("keep_root_aliases", False)
        self.openai_mode = pxy.get("openai_compatible", False)
        self.only_openai = pxy.get("only_openai_tools", False) and self.openai_mode
        self.project_root = project_root
        self.mcp_servers = cfg.get("mcp_servers", {})

        logger.setLevel(logging.DEBUG)
        logger.debug(
            "Proxy init – openai=%s | only_openai=%s | keep_root=%s",
            self.openai_mode,
            self.only_openai,
            self.keep_root_aliases,
        )

        self.stream_manager = None
        self.running: Dict[str, Dict[str, Any]] = {}
        self._tmp_cfg: tempfile.NamedTemporaryFile | None = None
        self.openai_wrappers: Dict[str, Callable] = {}

    # ─────────────────────── bootstrap / shutdown ───────────────────────
    async def start_servers(self) -> None:
        if not (self.enabled and self.mcp_servers):
            logger.warning("Proxy disabled or no MCP servers configured")
            return

        stdio_cfg: Dict[str, Any] = {"mcpServers": {}}
        stdio, stdio_map = [], {}
        for name, opts in self.mcp_servers.items():
            if opts.get("type", "stdio") != "stdio":
                continue  # SSE not yet wired here
            stdio.append(name)
            stdio_map[len(stdio_map)] = name
            cwd = opts.get("location") or ""
            if cwd and not os.path.isabs(cwd):
                cwd = os.path.join(self.project_root, cwd)
            stdio_cfg["mcpServers"][name] = {
                "command": opts.get("command", "python"),
                "args": opts.get("args", []),
                "cwd": cwd,
            }

        if not stdio:
            logger.error("No stdio servers configured")
            return

        # Write minimal config for tool‑processor stdio launcher
        self._tmp_cfg = tempfile.NamedTemporaryFile(mode="w", delete=False)
        json.dump(stdio_cfg, self._tmp_cfg)
        self._tmp_cfg.flush()
        _, self.stream_manager = await setup_mcp_stdio(
            config_file=self._tmp_cfg.name,
            servers=stdio,
            server_names=stdio_map,
            namespace=self.ns_root,
        )

        for srv in stdio:
            self.running[srv] = {"wrappers": {}}

        await self._discover_and_wrap()

    async def stop_servers(self) -> None:
        if self.stream_manager:
            await self.stream_manager.close()
        if self._tmp_cfg:
            try:
                os.unlink(self._tmp_cfg.name)
            except OSError:
                pass

    # ───────────────────── internal helpers ─────────────────────
    async def _discover_and_wrap(self) -> None:
        """Query each server, build dot‑wrappers and OpenAI aliases."""
        if not self.stream_manager:
            return

        for server in self.running:
            for meta in await self.stream_manager.list_tools(server):
                tool_name = meta.get("name")
                if not tool_name:
                    continue

                dotted_ns = f"{self.ns_root}.{server}"
                dotted_full = f"{dotted_ns}.{tool_name}"

                # ------------------------------------------------------------------
                # 1) DOT‑NAME WRAPPER (internal + for OpenAI factory)                
                # ------------------------------------------------------------------
                wrapper = create_proxy_tool(
                    dotted_ns,
                    tool_name,
                    self.stream_manager,
                    meta,
                    only_openai_tools=self.only_openai,
                )
                self.running[server]["wrappers"][tool_name] = wrapper

                # Drop from public registry if underscore‑only mode
                if self.only_openai:
                    TOOLS_REGISTRY.pop(dotted_full, None)

                # ------------------------------------------------------------------
                # 2) UNDERSCORE ALIAS (OpenAI‑style)                                 
                # ------------------------------------------------------------------
                if not self.openai_mode:
                    continue

                under_name = to_openai_name(dotted_full)
                if under_name in self.openai_wrappers:
                    continue  # already done

                alias = create_openai_compatible_wrapper(dotted_full, wrapper)
                if alias is None:
                    continue  # metadata missing

                TOOLS_REGISTRY[under_name] = alias
                self.openai_wrappers[under_name] = alias
                logger.debug("Registered underscore wrapper: %s", under_name)

        # Diagnostics ---------------------------------------------------
        dot = [k for k in TOOLS_REGISTRY if "." in k and "_" not in k]
        under = [k for k in TOOLS_REGISTRY if "_" in k and "." not in k]
        logger.debug("Registry overview – dot: %d | under: %d", len(dot), len(under))

    # ───────────────────── public helpers ─────────────────────────
    def get_all_tools(self) -> Dict[str, Callable]:
        """Return all publicly exposed tools respecting config flags."""
        exposed: Dict[str, Callable] = dict(self.openai_wrappers)
        if not self.only_openai:
            for srv, info in self.running.items():
                for t_name, fn in info["wrappers"].items():
                    exposed[f"{self.ns_root}.{srv}.{t_name}"] = fn
        return exposed

    async def call_tool(self, name: str, **kw):
        """Convenience helper: call a tool by public name."""
        if "_" in name and "." not in name:  # convert underscore → dot
            server, tool = name.split("_", 1)
            name = f"{self.ns_root}.{server}.{tool}"
        srv = name.split(".")[1]
        tool = name.split(".")[-1]
        return await self.stream_manager.call_tool(tool, kw, srv)  # type: ignore[arg-type]
