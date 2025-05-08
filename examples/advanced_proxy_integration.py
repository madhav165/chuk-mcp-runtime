#!/usr/bin/env python
"""
Advanced Proxy Usage Example
============================

Boot ProxyServerManager directly (no run_runtime), list the wrapped
tools, call one programmatically, then drop into an interactive prompt
that echoes whatever you type via the remote echo tool.

Main changes vs. the original draft
-----------------------------------
1. **Single event-loop via `asyncio.run()`** – less boilerplate.
2. **Signal handling with `loop.add_signal_handler()`** – lets us await
   clean-up coroutines instead of cancelling tasks by hand.
3. **Graceful Ctrl-C** – first ^C stops the REPL and shuts down proxy
   servers; press again if you really want to kill the process.
4. **Removed unused imports / globals** – cleaner and easier to follow.
"""

from __future__ import annotations
import asyncio
import os
import sys
import signal
import traceback
from pathlib import Path
from typing import Dict

# ----------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# project imports
from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.server.logging_config import configure_logging
from chuk_mcp_runtime.proxy.manager import ProxyServerManager

# ---------------------------------------------------------------- config
HERE = Path(__file__).resolve().parent
CONFIG_YAML = HERE / "proxy_config.yaml"
if not CONFIG_YAML.exists():
    sys.exit(f"Config file not found: {CONFIG_YAML}")

# whether we want single-dot aliases like <tool name="proxy.echo" …/>
KEEP_ROOT_ALIASES = True


# ────────────────────────── helpers ──────────────────────────────
async def prompt_loop(echo_tool) -> None:
    """Interactive REPL that pipes input to the echo tool."""
    print("\n=== Interactive mode ===")
    print("Type a message (or 'exit' to quit)\n")

    loop = asyncio.get_running_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, lambda: input("> "))
        except (EOFError, KeyboardInterrupt):
            # Ctrl-D or Ctrl-C inside input(); exit loop gracefully
            print()
            break

        if line.lower() in {"exit", "quit", "q"}:
            break

        try:
            result = await echo_tool(message=line)
            print("Result:", result)
        except Exception as exc:
            print("⚠️  Tool error:", exc)
            traceback.print_exc()


async def main() -> None:
    # 1. load configuration -------------------------------------------------
    config = load_config([str(CONFIG_YAML)])
    configure_logging(config)

    # optionally keep proxy.<tool> aliases
    if KEEP_ROOT_ALIASES:
        config.setdefault("proxy", {})["keep_root_aliases"] = True

    project_root = find_project_root()
    proxy = ProxyServerManager(config, project_root)

    # install Ctrl-C handler before starting servers
    stop_event = asyncio.Event()

    def _handle_interrupt() -> None:
        if not stop_event.is_set():
            print("\nStopping… (press Ctrl-C again to force)")
            stop_event.set()
        else:
            print("\nForce exiting!")
            os._exit(1)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_interrupt)

    # 2. start proxy servers -------------------------------------------------
    print("Booting proxy layer…")
    await proxy.start_servers()

    # 3. show inventory ------------------------------------------------------
    print(f"\nRunning servers: {', '.join(proxy.running_servers.keys()) or 'None'}")

    tools: Dict[str, callable] = proxy.get_all_tools()
    print(f"Wrapped tools   : {len(tools)}")
    for t in tools:
        print("  •", t)

    # we’ll use the echo tool for the demo
    echo_tool_name = "proxy.echo2.echo"
    if echo_tool_name not in tools:
        print(f"Echo tool '{echo_tool_name}' not found; aborting.")
        await proxy.stop_servers()
        return

    # 4. one programmatic call ----------------------------------------------
    print("\n=== Direct call ===")
    res = await tools[echo_tool_name](message="Hello via direct call!")
    print("Result:", res)

    # 5. interactive loop ----------------------------------------------------
    await prompt_loop(tools[echo_tool_name])

    # wait for external stop request or just exit
    if not stop_event.is_set():
        stop_event.set()

    await proxy.stop_servers()
    print("Proxy layer shut down cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Should only reach here on a *second* Ctrl-C during shutdown
        print("\nForce-terminated by user.")
