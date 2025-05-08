#!/usr/bin/env python
# examples/proxy_server_example.py
"""
Proxy round-trip demo driven by proxy_config.yaml.

* Boots the echo2 MCP server via ProxyServerManager.
* Shows the registry grouped by namespace.
* Calls proxy.echo2.echo directly through its wrapper.
* Calls proxy.echo via an LLM-style <tool …/> tag and process_text().

This script forces `proxy.keep_root_aliases = true` at runtime so that
the single-dot alias proxy.<tool> survives the proxy manager’s pruning
step. Nothing else in the config file needs to change.
"""

from __future__ import annotations
import asyncio
import os
import sys
from typing import Dict

# ------------------------------------------------------------------ paths
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_tool_processor.registry import ToolRegistryProvider

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_YAML = os.path.join(HERE, "proxy_config.yaml")


async def main() -> None:
    # 1) load config and force keep_root_aliases ---------------------------
    config = load_config([CONFIG_YAML])
    config.setdefault("proxy", {})["keep_root_aliases"] = True

    # 2) start the proxy manager ------------------------------------------
    proxy = ProxyServerManager(config, find_project_root())
    await proxy.start_servers()

    try:
        # 3) dump registry --------------------------------------------------
        registry = ToolRegistryProvider.get_registry()
        grouped: Dict[str, list[str]] = {}
        for ns, name in registry.list_tools():
            grouped.setdefault(ns, []).append(name)

        print("\n=== Registry grouped by namespace ===")
        for ns, names in grouped.items():
            print(f"{ns} ({len(names)} tool(s))")
            for n in names:
                print("  •", n)

        # 4) call wrapper directly (proxy.echo2.echo) -----------------------
        wrapper = proxy.get_all_tools()["proxy.echo2.echo"]
        result = await wrapper(message="Hello from wrapper call!")
        print("\n=== wrapper round-trip ===")
        print("Result ->", result)

        # 5) LLM-style tag using single-dot alias proxy.echo ----------------
        tag = '<tool name="proxy.echo" args=\'{"message": "Hi via <tool> tag"}\'/>'
        llm_results = await proxy.process_text(tag)
        print("\n=== process_text() result ===")
        for res in llm_results:
            print("Tool:", res.tool, "| Result:", res.result, "| Error:", res.error)

    finally:
        await proxy.stop_servers()


if __name__ == "__main__":
    asyncio.run(main())
