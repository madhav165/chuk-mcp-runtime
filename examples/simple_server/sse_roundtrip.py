"""
Spawn the example MCP server (SSE mode) in a subprocess, then perform an
initialize + list_tools round-trip using httpx.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Dict

import httpx
from httpx import Response

HOST, PORT = "127.0.0.1", 8080
BASE = f"http://{HOST}:{PORT}"
SSE_URL = f"{BASE}/sse"
MSG_URL = f"{BASE}/messages"


# ---------- helpers ----------------------------------------------------
def rpc(msg_id: int, method: str, params: Dict | None = None) -> Dict:
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}


async def read_event(stream: Response) -> Dict:
    """Read the next SSE data event."""
    async for line in stream.aiter_lines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
        if line == "":
            continue  # event delimiter
    raise RuntimeError("SSE stream closed unexpectedly")


# ---------- main -------------------------------------------------------
async def main() -> None:
    server_script = Path(__file__).with_name("main.py").resolve()

    # 1) launch server subprocess
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(server_script),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    try:
        # 2) wait until the /sse endpoint responds
        async with httpx.AsyncClient() as probe:
            for _ in range(30):
                try:
                    r = await probe.get(SSE_URL, headers={"Accept": "text/event-stream"})
                    if r.status_code == 200:
                        r.close()
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError("Server did not start in time")

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", SSE_URL) as sse:
                # -- initialize --
                await client.post(MSG_URL, json=rpc(0, "initialize"))
                print("initialize →", json.dumps(await read_event(sse)))

                # -- list_tools --
                await client.post(MSG_URL, json=rpc(1, "list_tools"))
                print("list_tools →", json.dumps(await read_event(sse)))

    finally:
        proc.terminate()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5)
        print("Subprocess exited with code", proc.returncode)


if __name__ == "__main__":
    asyncio.run(main())
