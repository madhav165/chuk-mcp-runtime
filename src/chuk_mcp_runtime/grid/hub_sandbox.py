# chuk_mcp_runtime/grid/hub_sandbox.py
"""
Hub ↔︎ Sandbox integration - transport-agnostic **with shared session store registry**
==============================================================================

All hubs and sandboxes already depend on *one* session store picked via
``SESSION_PROVIDER`` (memory or Redis by default).  This revision drops
the dedicated Redis client and re-uses that **same provider** to publish
which hub “owns” every sandbox.

Registry rules
--------------
* One key per sandbox: ``sbx:<sandbox_id>`` → JSON blob
  ``{"hub": HUB_ID, "transport": "sse", "endpoint": "…", "ts": …}``
* Stored with a long TTL (24h) so the memory provider keeps it alive;
  the owning hub *deletes* the key when the stream closes.
* Every hub resolves remote sandboxes through the provider before
  deciding whether to **proxy** the call to another hub.
```
"""
from __future__ import annotations

import asyncio, json, os, time, urllib.parse
from typing import Dict, Tuple, Optional, Callable, AsyncContextManager

from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool, TOOLS_REGISTRY
from chuk_mcp_runtime.proxy.tool_wrapper import create_proxy_tool
from chuk_mcp_runtime.server.logging_config import get_logger
from chuk_mcp_runtime.session import provider_factory  # ← reuse existing providers

logger = get_logger("hub.register")

# ---------------------------------------------------------------------------
# Session‑store helpers (works with memory *and* Redis providers)
# ---------------------------------------------------------------------------

_SBXPREFIX = "sbx:"
_TTL = 24 * 3600  # 24 h – long enough for reconnects, short for stale GC

_session_factory: Callable[[], AsyncContextManager] | None = None
async def _get_session_factory():
    global _session_factory  # noqa: PLW0603
    if _session_factory is None:
        _session_factory = provider_factory.factory_for_env()
    return _session_factory

async def _registry_put(sbx_id: str, record: dict):
    factory = await _get_session_factory()
    async with factory() as sess:
        await sess.setex(f"{_SBXPREFIX}{sbx_id}", _TTL, json.dumps(record))

async def _registry_get(sbx_id: str) -> Optional[dict]:
    factory = await _get_session_factory()
    async with factory() as sess:
        raw = await sess.get(f"{_SBXPREFIX}{sbx_id}")
    return None if raw is None else json.loads(raw)

async def _registry_del(sbx_id: str):
    factory = await _get_session_factory()
    async with factory() as sess:
        if hasattr(sess, "delete"):
            await sess.delete(f"{_SBXPREFIX}{sbx_id}")
        else:  # memory provider pre‑TTL cleanup
            await sess.setex(f"{_SBXPREFIX}{sbx_id}", 1, "{}")

# ---------------------------------------------------------------------------
# Misc constants
# ---------------------------------------------------------------------------

_HUB_ID = os.getenv("HUB_ID", os.getenv("POD_NAME", "hub"))

# ---------------------------------------------------------------------------
# Transport dialer (SSE / stdio‑TCP / WebSocket)
# ---------------------------------------------------------------------------

async def _dial(endpoint: str, transport: str):
    transport = transport.lower()
    if transport == "sse":
        from mcp.lowlevel.client import connect_sse
        return await connect_sse(endpoint)

    if transport == "stdio":
        if endpoint.startswith("tcp://"):
            ep = urllib.parse.urlparse(endpoint)
            host, port = ep.hostname, ep.port
        else:
            host, port = endpoint.split(":", 1)
            port = int(port)
        return await asyncio.open_connection(host, int(port))

    if transport == "ws":
        import websockets  # type: ignore
        uri = endpoint.replace("http://", "ws://").replace("https://", "wss://")
        ws = await websockets.connect(uri)
        reader = asyncio.StreamReader()
        proto = websockets.streams.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_accepted_socket(proto, ws.transport.get_extra_info("socket"))
        writer = asyncio.StreamWriter(ws.transport, proto, reader, loop)
        return reader, writer

    raise ValueError(f"Unsupported transport '{transport}'")

# Active streams keyed by sandbox_id
_SANDBOX_STREAMS: Dict[str, Tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}

# ---------------------------------------------------------------------------
# Hub‑side tool: receive registration, create wrappers, write registry entry
# ---------------------------------------------------------------------------

@mcp_tool(name="hub.register_sandbox", description="Register a sandbox with this hub and expose its tools.")
async def register_sandbox(*, sandbox_id: str, endpoint: str, transport: str = "sse") -> str:  # noqa: D401
    reader, writer = await _dial(endpoint, transport)
    _SANDBOX_STREAMS[sandbox_id] = (reader, writer)
    logger.info("Sandbox %s connected via %s", sandbox_id, transport)

    # ---- list tools -----------------------------------------------------
    writer.write(b'{"role":"list_tools"}\n')
    await writer.drain()
    tools = json.loads(await reader.readline())["result"]

    ns_root = f"sbx.{sandbox_id}"
    for meta in tools:
        tname = meta["name"]
        fq = f"{ns_root}.{tname}"
        wrapper = await create_proxy_tool(ns_root, tname, None, meta)
        wrapper._owning_hub = _HUB_ID  # type: ignore[attr-defined]
        TOOLS_REGISTRY[fq] = wrapper

    # ---- write to shared registry --------------------------------------
    await _registry_put(sandbox_id, {
        "hub": _HUB_ID,
        "transport": transport,
        "endpoint": endpoint,
        "ts": int(time.time()),
    })

    # ---- background pump ------------------------------------------------
    async def _pump():
        try:
            while await reader.readline():
                pass
        finally:
            _SANDBOX_STREAMS.pop(sandbox_id, None)
            for key in list(TOOLS_REGISTRY):
                if key.startswith(f"sbx.{sandbox_id}."):
                    TOOLS_REGISTRY.pop(key, None)
            await _registry_del(sandbox_id)
            logger.warning("Sandbox %s disconnected", sandbox_id)

    asyncio.create_task(_pump())
    return f"registered {len(tools)} tool(s) from {sandbox_id} via {transport} on hub {_HUB_ID}"

# ---------------------------------------------------------------------------
# Helper: cross‑hub proxy (call from MCPServer.call_tool)
# ---------------------------------------------------------------------------

async def proxy_call_tool(name: str, arguments: dict, *, self_execute):
    """Execute locally or forward to owning hub based on registry."""

    # Local fast path ----------------------------------------------------
    if name in TOOLS_REGISTRY:
        owner = getattr(TOOLS_REGISTRY[name], "_owning_hub", _HUB_ID)
        if owner == _HUB_ID:
            return await self_execute(name, arguments)

    # Only sandbox tools can be proxied
    if not name.startswith("sbx."):
        raise ValueError(f"Tool {name} not found locally and no sbx prefix")

    sbx_id = name.split(".")[1]
    rec = await _registry_get(sbx_id)
    if rec is None:
        raise ValueError(f"No registry entry for sandbox {sbx_id}")
    owner_hub = rec["hub"]

    if owner_hub == _HUB_ID:
        # we own it but wrapper missing (race during reconnect)
        return await self_execute(name, arguments)

    # HTTP proxy to owning hub ------------------------------------------
    base_tpl = os.getenv("HUB_BASE_URL_TEMPLATE", "http://{hub}:8000")
    url = f"{base_tpl.format(hub=owner_hub)}/call/{name}"

    import aiohttp
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=arguments) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Upstream hub {owner_hub} error {resp.status}: {await resp.text()}")
            return await resp.json()

# ---------------------------------------------------------------------------
# Sandbox‑side bootstrap
# ---------------------------------------------------------------------------

async def register_with_hub() -> None:
    """Schedule this coroutine once the sandbox runtime is listening."""
    import aiohttp

    sbx_id = os.getenv("SANDBOX_ID")
    if not sbx_id:
        logger.error("SANDBOX_ID unset – skipping registration")
        return

    hub_addr = os.getenv("HUB_ADDR", "http://hub:8000")
    hub_token = os.getenv("HUB_TOKEN", "")
    transport = os.getenv("SBX_TRANSPORT", "sse").lower()

    endpoint = os.getenv("HUB_URL") or _infer_endpoint(transport)
    if endpoint is None:
        return

    payload = {"sandbox_id": sbx_id, "endpoint": endpoint, "transport": transport}
    headers = {"Authorization": f"Bearer {hub_token}"} if hub_token else {}

    try:
        async with aiohttp.ClientSession(headers=headers) as sess:
            async with sess.post(f"{hub_addr}/call/hub.register_sandbox", json=payload) as resp:
                txt = await resp.text()
                if resp.status == 200:
                    logger.info("[sandbox %s] hub: %s", sbx_id, txt)
                else:
                    logger.error("Hub error %s: %s", resp.status, txt)
    except Exception as exc:
        logger.exception("Failed to register with hub: %s", exc)


def _infer_endpoint(transport: str) -> Optional[str]:
    pod_ip = os.getenv("POD_IP") or os.getenv("HOSTNAME")
    if not pod_ip:
        logger.error("Cannot infer sandbox endpoint – set HUB_URL")
        return None
    if transport == "sse":
        return f"http://{pod_ip}:8000/sse"
    if transport == "stdio":
        return f"tcp://{pod_ip}:9000"
    if transport == "ws":
        return f"ws://{pod_ip}:8765/ws"
    logger.error("Unknown transport '%s'", transport)
    return None
