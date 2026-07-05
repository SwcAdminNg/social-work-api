from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import email_service
from app.core.security import generate_opaque_token, hash_password, hash_token
from app.modules.admin.dto import AcceptAdminInviteRequestDTO, InviteAdminRequestDTO
from app.modules.auth.entity import AdminInviteToken
from app.modules.auth.repository import AdminInviteTokenRepository
from app.modules.user.entity import User, UserTypeEnum
from app.modules.user.repository import UserRepository


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.invite_tokens = AdminInviteTokenRepository(session)

    async def invite_admin(self, inviter: User, payload: InviteAdminRequestDTO) -> User:
        if await self.users.email_exists(payload.email):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")
        if await self.users.username_exists(payload.username):
            raise HTTPException(status.HTTP_409_CONFLICT, "Username is already taken")

        user = User(
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email.lower(),
            username=payload.username,
            phone_number=payload.phone_number,
            platform=payload.platform,
            user_type=UserTypeEnum.ADMIN,
            hashed_password=None,
            is_active=False,
            created_by=inviter.id,
        )

        try:
            await self.users.create(user)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Email or username is already taken")

        raw_token = generate_opaque_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.admin_invite_token_expire_minutes
        )
        invite_token = AdminInviteToken(
            user_id=user.id, token_hash=hash_token(raw_token), expires_at=expires_at
        )
        await self.invite_tokens.create(invite_token)
        await self.session.commit()

        invite_link = f"{settings.frontend_url}/accept-admin-invite?token={raw_token}"
        await email_service.send_admin_invite_email(user.email, user.first_name, invite_link)

        return user

    async def accept_invite(self, payload: AcceptAdminInviteRequestDTO) -> None:
        token_hash = hash_token(payload.token)
        stored_token = await self.invite_tokens.get_valid_by_hash(token_hash)

        if stored_token is None or stored_token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired invite token")

        user = await self.users.get_by_id(stored_token.user_id)
        if user is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired invite token")

        user.hashed_password = await hash_password(payload.password)
        user.is_active = True
        await self.invite_tokens.mark_used(stored_token)
        await self.session.commit()
