#!/usr/bin/env python
"""
examples/show_registry.py
-------------------------

List all MCP tools grouped by namespace, then run a quick echo round-trip.

* Reads `proxy_config.yaml` next to this script (or a custom `--config` path).
* Falls back to project-root `stdio_proxy_config.yaml` if the default is missing.
* Works in both dot-name and underscore (OpenAI) modes.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Dict, List, Tuple

# ── project path -----------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── internal imports -------------------------------------------------
from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.proxy.manager import ProxyServerManager

try:
    from chuk_tool_processor.registry import ToolRegistryProvider
except ModuleNotFoundError:  # optional
    ToolRegistryProvider = None  # type: ignore

# ── helpers ----------------------------------------------------------
def _canonical_name(entry: object) -> str:
    """Return a display-ready name for a list_tools() entry."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):           # metadata dict
        return entry.get("name", str(entry))
    if hasattr(entry, "_mcp_tool"):       # function with metadata
        return entry._mcp_tool.name       # type: ignore[attr-defined]
    return getattr(entry, "__name__", str(entry))


def group_registry() -> Dict[str, List[str]]:
    """Group tools by namespace, suppressing duplicates in 'default'."""
    grouped: Dict[str, List[str]] = {}
    if not ToolRegistryProvider:
        return grouped

    seen: set[str] = set()
    reg = ToolRegistryProvider.get_registry()

    for ns, entry in reg.list_tools():
        ns = ns or "(no-ns)"
        display = _canonical_name(entry)
        canonical = display.split(".")[-1]

        if ns == "default" and canonical in seen:
            continue
        seen.add(canonical)
        grouped.setdefault(ns, []).append(display)

    for tools in grouped.values():
        tools.sort()
    return grouped


def find_echo_tool(wrappers: Dict[str, callable]) -> Tuple[str, callable]:
    for name, fn in wrappers.items():
        if "echo" in name.lower():
            return name, fn
    raise RuntimeError("No echo tool found")

# ── main async demo --------------------------------------------------
async def main(config_path: str) -> None:
    if not os.path.exists(config_path):
        alt = os.path.join(ROOT, "stdio_proxy_config.yaml")
        if os.path.exists(alt):
            print(f"⚠️  {config_path} not found – falling back to {alt}")
            config_path = alt
        else:
            raise FileNotFoundError(f"Config file not found: {config_path}")

    config = load_config([config_path])
    print(f"Loaded config → {config_path}")

    proxy = ProxyServerManager(config, find_project_root())
    await proxy.start_servers()

    try:
        # registry dump
        grouped = group_registry()
        if grouped:
            print("\n=== Registry grouped by namespace ===")
            for ns, tools in grouped.items():
                print(f"{ns} ({len(tools)} tool(s))")
                for t in tools:
                    print("  •", t)

        # wrappers from proxy
        wrappers = proxy.get_all_tools()
        print(
            f"\nproxy.get_all_tools() → {len(wrappers)} "
            f"(openai_mode={proxy.openai_mode})"
        )
        for w in sorted(wrappers):
            print("  •", w)

        # echo demo
        try:
            echo_name, echo_fn = find_echo_tool(wrappers)
            result = await echo_fn(message="Hello from show_registry demo!")
            print(f"\n=== {echo_name} round-trip ===")
            print("Result ->", result)
        except RuntimeError:
            print("\n(no echo tool found for round-trip demo)")

    finally:
        await proxy.stop_servers()

# ── CLI --------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "-c",
        "--config",
        default=os.path.join(os.path.dirname(__file__), "proxy_config.yaml"),
        help="YAML config path (default: proxy_config.yaml next to script)",
    )
    asyncio.run(main(ap.parse_args().config))
