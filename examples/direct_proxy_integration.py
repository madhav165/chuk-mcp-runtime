#!/usr/bin/env python
# examples/direct_proxy_integration.py
"""
Direct Proxy Integration Example
--------------------------------

Boot the CHUK MCP Runtime – **with the proxy layer enabled –** by calling
`run_runtime()` directly.  The runtime blocks until you press <Ctrl-C>.

Key fixes vs. the original draft
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **Pass `default_config` –** that’s how you inject extra settings
   (e.g. forcing the proxy on).  
2. **Let `run_runtime()` handle SIGINT/SIGTERM** – the function already
   installs its own graceful-shutdown logic, so the manual signal
   handler / global flag isn’t needed.  
3. **No stray `asyncio` or `threading` imports** – they weren’t used.  
4. **Simpler `sys.path` tweak** – add the repo root once and only if
   needed.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

# ── locate project root so `import chuk_mcp_runtime` works -------------
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chuk_mcp_runtime.entry import run_runtime

# ── path to proxy_config.yaml (sits next to this file) -----------------
CONFIG_YAML = Path(__file__).with_name("proxy_config.yaml")

if not CONFIG_YAML.exists():
    sys.exit(f"Config file not found: {CONFIG_YAML}")

if __name__ == "__main__":
    print("Starting CHUK MCP Runtime with proxy support …")
    print(f"Config file: {CONFIG_YAML}\nPress Ctrl-C to stop.\n")

    # Extra tweaks you want *in addition* to whatever is in YAML
    default_cfg = {
        "proxy": {
            "enabled": True,          # just to be explicit
            # "keep_root_aliases": True,   # uncomment if you want proxy.<tool> aliases
        }
    }

    try:
        # Blocks until KeyboardInterrupt or an uncaught exception
        run_runtime(
            config_paths=[str(CONFIG_YAML)],
            default_config=default_cfg,
        )
    except KeyboardInterrupt:
        # run_runtime already logs a message; this is just extra UX sugar
        print("\nShutdown requested — goodbye!")
