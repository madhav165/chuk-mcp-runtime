#!/usr/bin/env python
"""
examples/openai_compatibility_demo.py
-------------------------------------

Minimal, deterministic demo of ProxyServerManager *in OpenAI-only mode*.

Run:

    uv run examples/openai_compatibility_demo.py --only-openai-tools
"""

from __future__ import annotations
import argparse, asyncio, json, logging, os, tempfile, sys
from pathlib import Path
from typing import Dict

# ── logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(name)s: %(message)s",
)
LOG = logging.getLogger("openai_demo")

# ── import path ───────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── internal imports ──────────────────────────────────────────────────
from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_mcp_runtime.server.config_loader import load_config

try:
    from chuk_tool_processor.registry import ToolRegistryProvider
except ModuleNotFoundError:
    ToolRegistryProvider = None  # type: ignore

try:
    from chuk_mcp_runtime.common.openai_compatibility import OpenAIToolsAdapter
except ModuleNotFoundError:
    OpenAIToolsAdapter = None  # type: ignore


# ───────────────────────── helpers ────────────────────────────────────
def fresh_registry() -> None:
    """Wipe the global ToolRegistryProvider (so no stale dot tools remain)."""
    if not ToolRegistryProvider:
        return
    reg = ToolRegistryProvider.get_registry()
    #  new API: reg.clear()  – old API: touch internals
    cleared = False
    if hasattr(reg, "clear"):
        reg.clear()             # type: ignore[attr-defined]
        cleared = True
    else:
        for attr in ("_tools", "_metadata"):
            bucket = getattr(reg, attr, None)
            if isinstance(bucket, dict):
                bucket.clear()
                cleared = True
    if cleared:
        LOG.debug("ToolRegistryProvider wiped")


def tmp_cfg(only_openai: bool) -> Path:
    """Write a one-off JSON config that starts *only* the time server."""
    cfg: Dict = {
        "proxy": {
            "enabled": True,
            "namespace": "proxy",
            "openai_compatible": True,
            "keep_root_aliases": False,
            "only_openai_tools": only_openai,
        },
        "mcp_servers": {
            "time": {
                "type": "stdio",
                "command": "uvx",
                "args": ["mcp-server-time", "--local-timezone", "America/New_York"],
            }
        },
    }
    fd, name = tempfile.mkstemp(suffix=".json", text=True)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    LOG.info("config → %s", name)
    return Path(name)


async def demo(only_openai_tools: bool, debug: bool) -> None:
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    fresh_registry()  # ensure a clean slate

    cfg = tmp_cfg(only_openai_tools)
    proxy = ProxyServerManager(load_config([str(cfg)]), str(ROOT))
    await proxy.start_servers()

    try:
        tools = proxy.get_all_tools()  # underscore aliases only
        print(f"\nproxy.get_all_tools() → {len(tools)}")
        for t in sorted(tools):
            print(" ", t)

        # ── call the two tools correctly ──────────────────────────────
        print("\n• demo calls")
        res_now = await tools["time_get_current_time"](timezone="America/New_York")
        print("  time_get_current_time →", res_now)

        res_conv = await tools["time_convert_time"](
            source_timezone="America/New_York",
            time="15:30",
            target_timezone="Europe/London",
        )
        print("  time_convert_time      →", res_conv)

        # ── OpenAI schema dump ────────────────────────────────────────
        if OpenAIToolsAdapter:
            schema = OpenAIToolsAdapter().get_openai_tools_definition()
            print(f"\nOpenAI schema objects ({len(schema)})")
            for s in schema:
                print("  •", s["function"]["name"])
        else:
            print("\n(OpenAIToolsAdapter not installed)")

    finally:
        await proxy.stop_servers()
        cfg.unlink(missing_ok=True)
        print("\n🛑 proxy shut down – temp config deleted.")


# ───────────────────────── main ───────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-openai-tools", action="store_true")
    ap.add_argument("--debug", action="store_true")
    asyncio.run(demo(**vars(ap.parse_args())))
