import os
import jwt
from jwt import PyJWTError
from jwt.exceptions import ExpiredSignatureError

from typing import Optional
from starlette.exceptions import HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "my-test-key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


async def validate_token(token: str) -> dict:
    try:
        # Decode and validate token
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            # options={"require": ["exp"]},  # Require expiration
        )
        payload["token"] = token
        return payload  # Contains the claims (e.g., user info)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except PyJWTError:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
