# chuk_mcp_runtime/entry.py
"""
Entry point for the CHUK MCP Runtime – async-native, proxy-aware,
with automatic chuk_artifacts integration.
"""
from __future__ import annotations

import asyncio
import os
import sys
from inspect import iscoroutinefunction
from typing import Any, Iterable, List, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()  


from chuk_mcp_runtime.common.mcp_tool_decorator import (
    TOOLS_REGISTRY,               # global “name → wrapper”
    initialize_tool_registry,
)
from chuk_mcp_runtime.common.openai_compatibility import (
    initialize_openai_compatibility,
)
from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_mcp_runtime.server.config_loader import find_project_root, load_config
from chuk_mcp_runtime.server.logging_config import configure_logging, get_logger
from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.server.server_registry import ServerRegistry
from chuk_mcp_runtime.tools import get_artifact_tools

# ── NEW: session-tool import (gracefully absent when not compiled in)
try:
    from chuk_mcp_runtime.tools import (
        register_session_tools,              # noqa: F401
        SESSION_TOOLS_AVAILABLE,
    )
except ImportError:  # session helper family stripped at build time
    SESSION_TOOLS_AVAILABLE = False
    async def register_session_tools(_: dict[str, Any]):  # type: ignore[override]
        return False

logger = get_logger("chuk_mcp_runtime.entry")

# ───────────────────────────── chuk_artifacts support ──────────────────────
try:
    from chuk_mcp_runtime.tools import (
        ARTIFACTS_TOOLS_AVAILABLE as _ARTIFACTS_TOOLS_AVAILABLE,
        register_artifacts_tools as _register_artifact_tools,
    )

    async def register_artifact_tools(cfg: dict[str, Any]):
        await _register_artifact_tools(cfg)

    CHUK_ARTIFACTS_AVAILABLE = _ARTIFACTS_TOOLS_AVAILABLE
except ImportError:               # chuk_artifacts not installed
    CHUK_ARTIFACTS_AVAILABLE = False
    async def register_artifact_tools(_: dict[str, Any]):  # noqa: D401
        pass

HAS_PROXY_SUPPORT = True          # tests may override


def _need_proxy(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("proxy", {}).get("enabled")) and HAS_PROXY_SUPPORT


# ───────────────────────── helper – artefact tools iterator ────────────────
def _iter_tools(container) -> Iterable[Tuple[str, Any]]:
    """Yield *(name, callable)* pairs from whatever get_artifact_tools() returns."""
    from chuk_mcp_runtime.tools import artifacts_tools as _at_mod

    if container is None:
        return ()

    if isinstance(container, dict):
        yield from (
            (n, f) for n, f in container.items() if hasattr(f, "_mcp_tool")
        )
        return ()

    if isinstance(container, (list, tuple, set)):
        for name in container:
            fn = TOOLS_REGISTRY.get(name) or getattr(_at_mod, name, None)
            if fn and hasattr(fn, "_mcp_tool"):
                yield name, fn
        return ()

    logger.debug(
        "Unexpected get_artifact_tools() return type: %s", type(container)
    )
    return ()


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────
async def run_runtime_async(
    config_paths: Optional[List[str]] = None,
    default_config: Optional[dict[str, Any]] = None,
    bootstrap_components: bool = True,
) -> None:
    """Boot the complete CHUK MCP runtime (async)."""
    # 1) config + logging
    cfg = load_config(config_paths, default_config)
    configure_logging(cfg)
    project_root = find_project_root()
    logger.debug("Project root resolved to %s", project_root)

    # 2) optional component bootstrap
    if bootstrap_components and not os.getenv("NO_BOOTSTRAP"):
        await ServerRegistry(project_root, cfg).load_server_components()

    # 3) decorator-based tool registry initialisation
    await initialize_tool_registry()

    # 4) artifact management wrappers
    if CHUK_ARTIFACTS_AVAILABLE:
        try:
            await register_artifact_tools(cfg)
            logger.info("chuk_artifacts tools registered successfully")
        except Exception as exc:      # pragma: no cover
            logger.warning("Artifact-tool registration failed: %s", exc)
    else:
        logger.info("chuk_artifacts not available – file tools skipped")

    # 4b) session-management wrappers  ←────────────── NEW BLOCK
    if SESSION_TOOLS_AVAILABLE:
        try:
            ok = await register_session_tools(cfg)
            logger.info(
                "Session-tool processing complete (%s)",
                "enabled" if ok else "disabled",
            )
        except Exception as exc:      # pragma: no cover
            logger.warning("Session-tool registration failed: %s", exc)

    # 5) optional OpenAI underscore wrappers
    try:
        if callable(initialize_openai_compatibility):
            if iscoroutinefunction(initialize_openai_compatibility):
                await initialize_openai_compatibility()
            else:
                initialize_openai_compatibility()
    except Exception as exc:          # pragma: no cover
        logger.warning("OpenAI-compat init failed: %s", exc)

    # 6) proxy layer (if any)
    proxy_mgr = None
    if _need_proxy(cfg):
        try:
            proxy_mgr = ProxyServerManager(cfg, project_root)
            await proxy_mgr.start_servers()
            if proxy_mgr.running:
                logger.info(
                    "Proxy layer enabled – %d server(s) booted",
                    len(proxy_mgr.running),
                )
        except Exception as exc:      # pragma: no cover
            logger.error("Proxy bootstrap error: %s", exc, exc_info=True)
            proxy_mgr = None

    # 7) local MCP server (explicit registry pass-through)
    mcp_server = MCPServer(cfg, tools_registry=TOOLS_REGISTRY)
    logger.info("Local MCP server '%s' starting",
                getattr(mcp_server, "server_name", "local"))

    # 7a) log tool count
    tool_total = len(TOOLS_REGISTRY)
    art_related = sum(
        1
        for n in TOOLS_REGISTRY
        if any(kw in n for kw in ("file", "upload", "write", "read", "list"))
    )
    logger.info("Tools in registry: %d total, %d artifact-related",
                tool_total, art_related)

    # 7b) (re)register artifact helpers, proxy tools, etc.
    for name, fn in _iter_tools(get_artifact_tools()):
        try:
            await mcp_server.register_tool(name, fn)
        except Exception as exc:      # pragma: no cover
            logger.error("Failed to register tool %s: %s", name, exc)

    if proxy_mgr and hasattr(proxy_mgr, "get_all_tools"):
        for name, fn in (await proxy_mgr.get_all_tools()).items():
            try:
                await mcp_server.register_tool(name, fn)
            except Exception as exc:  # pragma: no cover
                logger.error("Proxy tool %s registration error: %s", name, exc)

    # 7c) proxy text handler
    custom_handlers = None
    if proxy_mgr and hasattr(proxy_mgr, "process_text"):

        async def _handle_proxy_text(text: str):
            try:
                return await proxy_mgr.process_text(text)
            except Exception as exc:  # pragma: no cover
                logger.error("Proxy text handler error: %s", exc, exc_info=True)
                return [{"error": f"Proxy error: {exc}"}]

        custom_handlers = {"handle_proxy_text": _handle_proxy_text}

    # 8) serve-forever loop
    try:
        await mcp_server.serve(custom_handlers=custom_handlers)
    finally:
        if proxy_mgr:
            logger.info("Stopping proxy layer")
            await proxy_mgr.stop_servers()


# ───────────────────────── sync wrapper & CLI glue ─────────────────────────
def run_runtime(
    config_paths: Optional[List[str]] = None,
    default_config: Optional[dict[str, Any]] = None,
    bootstrap_components: bool = True,
) -> None:
    try:
        asyncio.run(
            run_runtime_async(
                config_paths=config_paths,
                default_config=default_config,
                bootstrap_components=bootstrap_components,
            )
        )
    except KeyboardInterrupt:
        logger.warning("Received Ctrl-C → shutting down")
    except Exception as exc:          # pragma: no cover
        logger.error("Uncaught exception: %s", exc, exc_info=True)
        raise


async def main_async(default_config: Optional[dict[str, Any]] = None) -> None:
    try:
        argv = sys.argv[1:]
        cfg_path = (
            os.getenv("CHUK_MCP_CONFIG_PATH")
            or (argv[argv.index("-c") + 1] if "-c" in argv else None)
            or (argv[argv.index("--config") + 1] if "--config" in argv else None)
            or (argv[0] if argv else None)
        )
        await run_runtime_async(
            config_paths=[cfg_path] if cfg_path else None,
            default_config=default_config,
        )
    except Exception as exc:          # pragma: no cover
        print(f"Error starting CHUK MCP server: {exc}", file=sys.stderr)
        sys.exit(1)


def main(default_config: Optional[dict[str, Any]] = None) -> None:
    try:
        asyncio.run(main_async(default_config))
    except KeyboardInterrupt:
        logger.warning("Received Ctrl-C → shutting down")
    except Exception as exc:          # pragma: no cover
        logger.error("Uncaught exception: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":            # python -m chuk_mcp_runtime.entry
    main()
