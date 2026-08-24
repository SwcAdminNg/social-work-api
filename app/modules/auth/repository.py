import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.modules.auth.entity import (
    AdminInviteToken,
    EmailOtpToken,
    PasswordResetToken,
    RefreshToken,
    TwoFactorPurposeEnum,
)


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RefreshToken)

    async def get_active_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = self._base_select().where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)


class PasswordResetTokenRepository(BaseRepository[PasswordResetToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PasswordResetToken)

    async def get_valid_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_used(self, token: PasswordResetToken) -> None:
        token.used_at = datetime.now(timezone.utc)
        await self.session.flush()


class AdminInviteTokenRepository(BaseRepository[AdminInviteToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AdminInviteToken)

    async def get_valid_by_hash(self, token_hash: str) -> AdminInviteToken | None:
        stmt = select(AdminInviteToken).where(
            AdminInviteToken.token_hash == token_hash,
            AdminInviteToken.used_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_used(self, token: AdminInviteToken) -> None:
        token.used_at = datetime.now(timezone.utc)
        await self.session.flush()


class EmailOtpTokenRepository(BaseRepository[EmailOtpToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EmailOtpToken)

    async def find_valid_by_hash(
        self, user_id: uuid.UUID, purpose: TwoFactorPurposeEnum, code_hash: str
    ) -> EmailOtpToken | None:
        stmt = select(EmailOtpToken).where(
            EmailOtpToken.user_id == user_id,
            EmailOtpToken.purpose == purpose,
            EmailOtpToken.code_hash == code_hash,
            EmailOtpToken.used_at.is_(None),
            EmailOtpToken.expires_at > datetime.now(timezone.utc),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_used(self, token: EmailOtpToken) -> None:
        token.used_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def invalidate_all(self, user_id: uuid.UUID, purpose: TwoFactorPurposeEnum) -> None:
        stmt = (
            update(EmailOtpToken)
            .where(
                EmailOtpToken.user_id == user_id,
                EmailOtpToken.purpose == purpose,
                EmailOtpToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)
