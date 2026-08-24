import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.user.entity import User, UserTypeEnum
from app.modules.user.repository import UserRepository

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_user_from_token(token: str, db: AsyncSession) -> User | None:
    """Decodes a raw JWT access token and loads the active user it belongs to, or
    None if the token is invalid/expired or the user is missing/inactive. Shared by
    `get_current_user` (Authorization header) and any WebSocket endpoint, which
    cannot set request headers on the handshake and so passes the token as a query
    param instead (see `app/modules/support/router.py`)."""
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access":
            return None
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None

    user = await UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        return None

    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    user = await get_user_from_token(credentials.credentials, db)
    if user is None:
        raise unauthorized

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    return await get_user_from_token(credentials.credentials, db)


async def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.user_type != UserTypeEnum.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return current_user


async def get_current_admin_or_instructor(current_user: User = Depends(get_current_user)) -> User:
    if current_user.user_type not in (UserTypeEnum.ADMIN, UserTypeEnum.INSTRUCTOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin or instructor access required")
    return current_user
