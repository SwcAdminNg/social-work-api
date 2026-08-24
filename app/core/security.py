import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

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


def create_interim_token(
    subject: str, token_type: str, expire_minutes: int, extra_claims: dict[str, Any] | None = None
) -> str:
    """Short-lived JWT used for multi-step flows (2FA setup/verification) that happen
    before a full access token can be issued. Carries its own `type` claim so it can
    never be mistaken for (or used as) a regular access token."""
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire_at, "type": token_type}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError (or a subclass) if the token is invalid/expired.
    Despite the name, this decodes any JWT minted by this module (access, refresh-pair
    companion, or interim 2FA tokens) since they all share the same secret/algorithm."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def generate_opaque_token() -> str:
    """A cryptographically random, URL-safe token used for refresh and password-reset
    tokens. Only its hash is ever persisted (see hash_token)."""
    return secrets.token_urlsafe(32)


def generate_numeric_code(length: int = 6) -> str:
    """A cryptographically random numeric code, e.g. for emailed 2FA codes."""
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_fernet() -> Fernet:
    key_material = (settings.totp_secret_encryption_key or settings.jwt_secret_key).encode("utf-8")
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(key_material).digest())
    return Fernet(derived_key)


def encrypt_secret(plain_text: str) -> str:
    """Reversibly encrypts a secret (e.g. a TOTP seed) at rest. Unlike passwords, TOTP
    secrets must be decryptable to verify codes, so they can't be one-way hashed."""
    return _get_fernet().encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_secret(cipher_text: str) -> str:
    try:
        return _get_fernet().decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Could not decrypt secret")
