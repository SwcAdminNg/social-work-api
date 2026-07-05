import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


import asyncio

def _hash_password_sync(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

async def hash_password(plain_password: str) -> str:
    return await asyncio.to_thread(_hash_password_sync, plain_password)


def _verify_password_sync(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

async def verify_password(plain_password: str, hashed_password: str) -> bool:
    return await asyncio.to_thread(_verify_password_sync, plain_password, hashed_password)


def create_access_token(
    subject: str, extra_claims: dict[str, Any] | None = None, extended: bool = False
) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    expire_minutes = (
        settings.extended_access_token_expire_minutes
        if extended
        else settings.access_token_expire_minutes
    )
    expires_delta = timedelta(minutes=expire_minutes)
    expire_at = datetime.now(timezone.utc) + expires_delta
    payload: dict[str, Any] = {"sub": subject, "exp": expire_at, "type": "access"}
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError (or a subclass) if the token is invalid/expired."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def generate_opaque_token() -> str:
    """A cryptographically random, URL-safe token used for refresh and password-reset
    tokens. Only its hash is ever persisted (see hash_token)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
