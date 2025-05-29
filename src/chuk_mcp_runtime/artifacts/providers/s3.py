# chuk_mcp_runtime/artifacts/providers/s3.py
import os, aioboto3
from typing import Optional


def client(
    *,
    endpoint_url: Optional[str] = None,
    region: Optional[str] = None,
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
):
    """
    Return an aioboto3 S3 client. Works with aioboto3 >= 12 (no global .client).
    """
    session = aioboto3.Session()
    return session.client(
        "s3",
        endpoint_url=endpoint_url or os.getenv("S3_ENDPOINT_URL"),
        region_name=region or os.getenv("AWS_REGION", "us-south"),
        aws_access_key_id=access_key or os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=secret_key or os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
