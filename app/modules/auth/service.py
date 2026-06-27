from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import email_service
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.auth.dto import (
    AuthSessionDTO,
    ForgotPasswordRequestDTO,
    LoginRequestDTO,
    RefreshTokenRequestDTO,
    ResetPasswordRequestDTO,
    SignUpRequestDTO,
    TokenPairDTO,
)
from app.modules.auth.entity import PasswordResetToken, RefreshToken
from app.modules.auth.repository import PasswordResetTokenRepository, RefreshTokenRepository
from app.modules.auth.username import generate_username_suggestions
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import User
from app.modules.user.repository import UserRepository


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.reset_tokens = PasswordResetTokenRepository(session)

    async def get_username_suggestions(self, first_name: str, last_name: str) -> list[str]:
        return await generate_username_suggestions(self.users, first_name, last_name)

    async def check_username_availability(self, username: str) -> bool:
        return not await self.users.username_exists(username)

    async def sign_up(self, payload: SignUpRequestDTO) -> AuthSessionDTO:
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
            user_type=payload.user_type,
            hashed_password=hash_password(payload.password),
        )

        try:
            await self.users.create(user)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Email or username is already taken")

        tokens = await self._issue_token_pair(user)
        return AuthSessionDTO(user=UserReadDTO.model_validate(user), tokens=tokens)

    async def login(self, payload: LoginRequestDTO) -> AuthSessionDTO:
        user = await self.users.get_by_email_or_username(payload.identifier)
        if user is None or user.hashed_password is None or not verify_password(
            payload.password, user.hashed_password
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated")

        user.last_login_at = datetime.now(timezone.utc)
        await self.users.update(user)
        await self.session.commit()

        tokens = await self._issue_token_pair(user)
        return AuthSessionDTO(user=UserReadDTO.model_validate(user), tokens=tokens)

    async def refresh(self, payload: RefreshTokenRequestDTO) -> TokenPairDTO:
        token_hash = hash_token(payload.refresh_token)
        stored_token = await self.refresh_tokens.get_active_by_hash(token_hash)

        if stored_token is None or stored_token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")

        user = await self.users.get_by_id(stored_token.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")

        # Rotate: revoke the used refresh token and issue a brand-new pair.
        await self.refresh_tokens.revoke(stored_token)
        tokens = await self._issue_token_pair(user)
        return tokens

    async def forgot_password(self, payload: ForgotPasswordRequestDTO) -> None:
        user = await self.users.get_by_email(payload.email)
        if user is None:
            # Don't reveal whether the email is registered.
            return

        raw_token = generate_opaque_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.password_reset_token_expire_minutes
        )
        reset_token = PasswordResetToken(
            user_id=user.id, token_hash=hash_token(raw_token), expires_at=expires_at
        )
        await self.reset_tokens.create(reset_token)
        await self.session.commit()

        reset_link = f"{settings.frontend_url}/reset-password?token={raw_token}"
        await email_service.send_password_reset_email(user.email, user.first_name, reset_link)

    async def reset_password(self, payload: ResetPasswordRequestDTO) -> None:
        token_hash = hash_token(payload.token)
        stored_token = await self.reset_tokens.get_valid_by_hash(token_hash)

        if stored_token is None or stored_token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token")

        user = await self.users.get_by_id(stored_token.user_id)
        if user is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token")

        user.hashed_password = hash_password(payload.new_password)
        await self.reset_tokens.mark_used(stored_token)
        await self.refresh_tokens.revoke_all_for_user(user.id)
        await self.session.commit()

    async def _issue_token_pair(self, user: User) -> TokenPairDTO:
        access_token, expires_in = create_access_token(subject=str(user.id))

        raw_refresh_token = generate_opaque_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        refresh_token = RefreshToken(
            user_id=user.id, token_hash=hash_token(raw_refresh_token), expires_at=expires_at
        )
        await self.refresh_tokens.create(refresh_token)
        await self.session.commit()

        return TokenPairDTO(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            expires_in=expires_in,
        )
