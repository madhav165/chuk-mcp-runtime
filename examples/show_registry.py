#!/usr/bin/env python
# examples/show_registry.py
"""
Show each MCP server as a “client namespace” in the CHUK registry.

Uses ONLY the config.yaml that lives next to this script.
"""

from __future__ import annotations
import asyncio, os, sys
from typing import Dict

# ── project imports -------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_tool_processor.registry import ToolRegistryProvider

# -------------------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "proxy_config.yaml")


async def main() -> None:
    # 1. load the YAML you provided
    config = load_config([CONFIG_PATH])
    project_root = find_project_root()

    # 2. start the proxy manager (boots echo2)
    proxy = ProxyServerManager(config, project_root)
    await proxy.start_servers()

    try:
        # 3. dump registry grouped by namespace (== MCP client/server)
        registry = ToolRegistryProvider.get_registry()
        grouped: Dict[str, list[str]] = {}
        for ns, name in registry.list_tools():
            grouped.setdefault(ns, []).append(name)

        print("\n=== Registry grouped by namespace ===")
        for ns, tools in grouped.items():
            print(f"{ns} ({len(tools)} tool(s))")
            for t in tools:
                print("  •", t)

        # 4) run one proxy call via the wrapper itself
        wrappers = proxy.get_all_tools()              # mapping fq-name → callable
        echo_wrapper = wrappers["proxy.echo2.echo"]   # async function
        result = await echo_wrapper(message="Hello from YAML-only demo!")
        print("\n=== proxy.echo2.echo round-trip ===")
        print("Result ->", result)

    finally:
        await proxy.stop_servers()


if __name__ == "__main__":
    asyncio.run(main())
