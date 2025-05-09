#!/usr/bin/env python
# examples/proxy_server_example.py
#!/usr/bin/env python
"""
examples/proxy_server_example.py
--------------------------------

Proxy round-trip demo driven by *proxy_config.yaml*.

• Boots the *echo2* MCP server via ``ProxyServerManager``.  
• Prints the registry grouped by namespace.  
• Calls the wrapper ``proxy.echo2.echo`` directly and shows the result.

The simplified ProxyServerManager now has a single switch:

    proxy.openai_compatible:
        false → dot wrappers (e.g. proxy.echo2.echo)
        true  → underscore wrappers (e.g. echo2_echo)

This demo assumes *openai_compatible: false* so dot names exist.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Dict, List

# ── project paths ----------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── internal imports -------------------------------------------------
from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.proxy.manager import ProxyServerManager

try:
    from chuk_tool_processor.registry import ToolRegistryProvider
except ModuleNotFoundError:  # optional
    ToolRegistryProvider = None  # type: ignore

# --------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_YAML = os.path.join(HERE, "proxy_config.yaml")


def group_registry() -> Dict[str, List[str]]:
    """Return registry grouped by namespace (if the provider is present)."""
    grouped: Dict[str, List[str]] = {}
    if not ToolRegistryProvider:
        return grouped

    for ns, name in ToolRegistryProvider.get_registry().list_tools():
        grouped.setdefault(ns or "(no-ns)", []).append(name)

    for tools in grouped.values():
        tools.sort()
    return grouped


async def main() -> None:
    # 1) load config (no keep_root_aliases anymore) --------------------
    config = load_config([CONFIG_YAML])
    project_root = find_project_root()

    # 2) start proxy manager ------------------------------------------
    proxy = ProxyServerManager(config, project_root)
    await proxy.start_servers()

    try:
        # 3) dump registry --------------------------------------------
        grouped = group_registry()
        print("\n=== Registry grouped by namespace ===")
        if grouped:
            for ns, names in grouped.items():
                print(f"{ns} ({len(names)} tool(s))")
                for n in names:
                    print("  •", n)
        else:
            print("(ToolRegistryProvider not installed)")

        # 4) call wrapper directly ------------------------------------
        wrappers = proxy.get_all_tools()
        dot_name = "proxy.echo2.echo"
        if dot_name not in wrappers:
            raise RuntimeError(
                f"{dot_name} not found – "
                "make sure openai_compatible is set to *false* in the YAML"
            )

        echo_wrapper = wrappers[dot_name]
        result = await echo_wrapper(message="Hello from wrapper call!")
        print("\n=== proxy.echo2.echo round-trip ===")
        print("Result ->", result)

    finally:
        await proxy.stop_servers()


if __name__ == "__main__":
    asyncio.run(main())
