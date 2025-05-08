#!/usr/bin/env python
"""
Proxy round-trip demo driven by proxy_config.yaml (no temp files).

* Boots the echo2 MCP server via ProxyServerManager.
* Prints the registry grouped by namespace.
* Calls proxy.echo2.echo through its wrapper.
* Calls proxy.echo via an LLM-style <tool …/> tag and process_text().
"""

from __future__ import annotations
import asyncio, os, sys
from typing import Dict

# ── imports ---------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_tool_processor.registry import ToolRegistryProvider

# locate YAML next to this script
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_YAML = os.path.join(HERE, "proxy_config.yaml")


async def main() -> None:
    # 1) start proxy manager
    config = load_config([CONFIG_YAML])
    proxy = ProxyServerManager(config, find_project_root())
    await proxy.start_servers()

    try:
        # 2) registry dump
        reg = ToolRegistryProvider.get_registry()
        grouped: Dict[str, list[str]] = {}
        for ns, name in reg.list_tools():
            grouped.setdefault(ns, []).append(name)

        print("\n=== Registry grouped by namespace ===")
        for ns, names in grouped.items():
            print(f"{ns} ({len(names)} tool(s))")
            for n in names:
                print("  •", n)

        # 3) wrapper call (two-level namespace -> proxy.echo2.echo)
        wrapper = proxy.get_all_tools()["proxy.echo2.echo"]
        result = await wrapper(message="Hello from wrapper call!")
        print("\n=== wrapper round-trip ===")
        print("Result ->", result)

        # 4) process_text() call with single-level namespace
        #    ToolProcessor splits on the *first* dot only: namespace=proxy, name=echo
        tag = '<tool name="proxy.echo" args=\'{"message": "Hi via <tool> tag"}\'/>'
        llm_results = await proxy.process_text(tag)
        print("\n=== process_text() result ===")
        for res in llm_results:
            print("Tool:", res.tool, "| Result:", res.result, "| Error:", res.error)

    finally:
        await proxy.stop_servers()


if __name__ == "__main__":
    asyncio.run(main())
