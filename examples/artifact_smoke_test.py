#!/usr/bin/env python3
# examples/artifact_runtime_check.py
"""
Smoke-test for the Artefact runtime layer (no image tools involved).

Workflow
--------
1. Build an async-context S3 factory via provider_factory
   (driven by ARTIFACT_PROVIDER env).
2. Instantiate ArtifactStore with that factory.
3. Upload "Hello, artefact!" (text/plain).
4. Read back metadata and a 60-second presigned URL.
5. Download the file via the presigned URL to prove it's reachable.
"""

import os, asyncio, aiohttp
from chuk_mcp_runtime.artifacts.provider_factory import factory_for_env
from chuk_mcp_runtime.artifacts import ArtifactStore
from dotenv import load_dotenv

# load environment
load_dotenv()


async def main() -> None:
    print("▶ Bootstrapping ArtifactStore …")

    store = ArtifactStore(
        bucket=os.getenv("ARTIFACT_BUCKET", "mcp-bucket"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        s3_factory=factory_for_env(),  # Call factory_for_env() to get the _make function
    )

    # 1. Upload a tiny artefact
    data = b"Hello, artefact!\n"
    artefact_id = await store.store(
        data=data,
        mime="text/plain",
        summary="runtime smoke-test text file",
        meta={"demo": True},
        filename="hello.txt",
    )
    print(f"   • Stored as artefact_id = {artefact_id}")

    # 2. Fetch metadata
    meta = await store.metadata(artefact_id)
    print("   • Metadata  :", meta)

    # 3. Get a presigned download URL
    url = await store.presign(artefact_id, expires=60)
    print("   • Presigned :", url)

    # 4. Prove the URL works (HTTP GET)
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url) as resp:
            body = await resp.text()
            print("   • Download  :", resp.status, body.strip())

    print("\n✅ Artefact runtime layer is working end-to-end.")


if __name__ == "__main__":
    asyncio.run(main())