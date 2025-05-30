# -*- coding: utf-8 -*-
# chuk_mcp_runtime/artifacts/__init__.py
"""
Convenient artifact storage with automatic .env loading.

Usage Examples
──────────────

**Zero-config setup (uses memory):**
```python
from chuk_mcp_runtime.artifacts import STORE

# Store an artifact
artifact_id = await STORE.store(
    data=b"Hello, world!",
    mime="text/plain",
    summary="A simple greeting"
)

# Retrieve it
data = await STORE.retrieve(artifact_id)
```

**Custom configuration:**
```python
from chuk_mcp_runtime.artifacts import ArtifactStore

# Custom store instance
store = ArtifactStore(
    storage_provider="s3",
    session_provider="redis"
)
```

**Environment-based configuration (.env file):**
```bash
# .env file
ARTIFACT_PROVIDER=s3
SESSION_PROVIDER=redis
ARTIFACT_BUCKET=my-bucket
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
SESSION_REDIS_URL=redis://localhost:6379/0
```

```python
# Python code - automatically loads .env
from chuk_mcp_runtime.artifacts import STORE  # Uses .env config
```
"""

from .store import ArtifactStore, ArtifactStoreError, ArtifactNotFoundError, ArtifactExpiredError
from .models import ArtifactEnvelope

# Auto-load .env and create default store instance
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Global store instance for convenience
STORE = ArtifactStore()

__all__ = [
    "ArtifactStore",
    "ArtifactStoreError", 
    "ArtifactNotFoundError",
    "ArtifactExpiredError",
    "ArtifactEnvelope",
    "STORE",
]