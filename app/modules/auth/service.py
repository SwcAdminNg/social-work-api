import base64
import io
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
import qrcode
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import email_service
from app.core.security import (
    create_access_token,
    create_interim_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    generate_numeric_code,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.auth.dto import (
    AuthSessionDTO,
    ForgotPasswordRequestDTO,
    LoginRequestDTO,
    LoginResponseDTO,
    RefreshTokenRequestDTO,
    ResetPasswordRequestDTO,
    SignUpRequestDTO,
    TokenPairDTO,
    TwoFactorChallengeDTO,
    TwoFactorStatusDTO,
    TwoFactorTotpSetupResponseDTO,
)
from app.modules.auth.entity import EmailOtpToken, PasswordResetToken, RefreshToken, TwoFactorPurposeEnum
from app.modules.auth.repository import (
    EmailOtpTokenRepository,
    PasswordResetTokenRepository,
    RefreshTokenRepository,
)
from app.modules.auth.username import generate_username_suggestions
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import TwoFactorMethodEnum, User
from app.modules.user.repository import UserRepository

TWO_FACTOR_SETUP_TOKEN_TYPE = "2fa_setup"
TWO_FACTOR_PENDING_TOKEN_TYPE = "2fa_pending"


def _build_qr_data_uri(data: str) -> str:
    image = qrcode.make(data)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.reset_tokens = PasswordResetTokenRepository(session)
        self.email_otp_tokens = EmailOtpTokenRepository(session)

    async def get_username_suggestions(self, first_name: str, last_name: str) -> list[str]:
        return await generate_username_suggestions(self.users, first_name, last_name)

    async def check_username_availability(self, username: str) -> bool:
        return not await self.users.username_exists(username)

    async def sign_up(self, payload: SignUpRequestDTO) -> LoginResponseDTO:
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
            hashed_password=await hash_password(payload.password),
        )

        try:
            await self.users.create(user)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Email or username is already taken")

        # New accounts must set up 2FA before they can obtain a token pair.
        challenge_token = self._issue_challenge_token(user, TWO_FACTOR_SETUP_TOKEN_TYPE)
        return LoginResponseDTO(
            status="two_factor_setup_required",
            challenge=TwoFactorChallengeDTO(challenge_token=challenge_token),
        )

    async def login(self, payload: LoginRequestDTO) -> LoginResponseDTO:
        user = await self.users.get_by_email_or_username(payload.identifier)
        if user is None or user.hashed_password is None or not await verify_password(
            payload.password, user.hashed_password
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated")
        if user.is_suspended:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been suspended")

        user.last_login_at = datetime.now(timezone.utc)
        await self.users.update(user)
        await self.session.commit()

        if not user.two_factor_enabled or user.two_factor_method is None:
            challenge_token = self._issue_challenge_token(user, TWO_FACTOR_SETUP_TOKEN_TYPE)
            return LoginResponseDTO(
                status="two_factor_setup_required",
                challenge=TwoFactorChallengeDTO(challenge_token=challenge_token),
            )

        challenge_token = self._issue_challenge_token(
            user, TWO_FACTOR_PENDING_TOKEN_TYPE, extra_claims={"extended": payload.keep_logged_in}
        )
        if user.two_factor_method == TwoFactorMethodEnum.EMAIL:
            await self._issue_and_send_email_code(user, TwoFactorPurposeEnum.LOGIN)

        return LoginResponseDTO(
            status="two_factor_verification_required",
            challenge=TwoFactorChallengeDTO(challenge_token=challenge_token, method=user.two_factor_method),
        )

    async def verify_login_2fa(self, challenge_token: str, code: str) -> AuthSessionDTO:
        decoded = self._decode_challenge_token(challenge_token, TWO_FACTOR_PENDING_TOKEN_TYPE)
        user = await self._load_active_user(decoded)

        if user.two_factor_method == TwoFactorMethodEnum.TOTP:
            self._verify_totp_code(user, code)
        else:
            await self._verify_email_code(user, code, TwoFactorPurposeEnum.LOGIN)

        extended = bool(decoded.get("extended", False))
        tokens = await self._issue_token_pair(user, extended=extended)
        return AuthSessionDTO(user=UserReadDTO.model_validate(user), tokens=tokens)

    async def resend_login_2fa_code(self, challenge_token: str) -> None:
        decoded = self._decode_challenge_token(challenge_token, TWO_FACTOR_PENDING_TOKEN_TYPE)
        user = await self._load_active_user(decoded)
        if user.two_factor_method != TwoFactorMethodEnum.EMAIL:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Resend is only available for email verification")
        await self._issue_and_send_email_code(user, TwoFactorPurposeEnum.LOGIN)

    # -- Forced setup (pre-login, resolved via a "2fa_setup" challenge token) --------

    async def start_totp_setup_forced(self, challenge_token: str) -> TwoFactorTotpSetupResponseDTO:
        decoded = self._decode_challenge_token(challenge_token, TWO_FACTOR_SETUP_TOKEN_TYPE)
        user = await self._load_active_user(decoded)
        return await self._start_totp_setup(user)

    async def confirm_totp_setup_forced(self, challenge_token: str, code: str) -> AuthSessionDTO:
        decoded = self._decode_challenge_token(challenge_token, TWO_FACTOR_SETUP_TOKEN_TYPE)
        user = await self._load_active_user(decoded)
        await self._confirm_totp_setup(user, code)
        tokens = await self._issue_token_pair(user)
        return AuthSessionDTO(user=UserReadDTO.model_validate(user), tokens=tokens)

    async def start_email_setup_forced(self, challenge_token: str) -> None:
        decoded = self._decode_challenge_token(challenge_token, TWO_FACTOR_SETUP_TOKEN_TYPE)
        user = await self._load_active_user(decoded)
        await self._issue_and_send_email_code(user, TwoFactorPurposeEnum.SETUP)

    async def confirm_email_setup_forced(self, challenge_token: str, code: str) -> AuthSessionDTO:
        decoded = self._decode_challenge_token(challenge_token, TWO_FACTOR_SETUP_TOKEN_TYPE)
        user = await self._load_active_user(decoded)
        await self._confirm_email_setup(user, code)
        tokens = await self._issue_token_pair(user)
        return AuthSessionDTO(user=UserReadDTO.model_validate(user), tokens=tokens)

    # -- Voluntary switch (already authenticated) -------------------------------------

    async def get_two_factor_status(self, user: User) -> TwoFactorStatusDTO:
        return TwoFactorStatusDTO(
            two_factor_enabled=user.two_factor_enabled, two_factor_method=user.two_factor_method
        )

    async def start_totp_setup(self, user: User) -> TwoFactorTotpSetupResponseDTO:
        return await self._start_totp_setup(user)

    async def confirm_totp_setup(self, user: User, code: str) -> TwoFactorStatusDTO:
        await self._confirm_totp_setup(user, code)
        return await self.get_two_factor_status(user)

    async def start_email_setup(self, user: User) -> None:
        await self._issue_and_send_email_code(user, TwoFactorPurposeEnum.SETUP)

    async def confirm_email_setup(self, user: User, code: str) -> TwoFactorStatusDTO:
        await self._confirm_email_setup(user, code)
        return await self.get_two_factor_status(user)

    # -- Shared 2FA internals ----------------------------------------------------------

    async def _start_totp_setup(self, user: User) -> TwoFactorTotpSetupResponseDTO:
        secret = pyotp.random_base32()
        user.totp_secret_encrypted = encrypt_secret(secret)
        await self.users.update(user)
        await self.session.commit()

        otpauth_url = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user.email, issuer_name=settings.totp_issuer_name
        )
        return TwoFactorTotpSetupResponseDTO(
            secret=secret, otpauth_url=otpauth_url, qr_code_data_uri=_build_qr_data_uri(otpauth_url)
        )

    async def _confirm_totp_setup(self, user: User, code: str) -> None:
        if not user.totp_secret_encrypted:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Start TOTP setup first")
        self._verify_totp_code(user, code)

        user.two_factor_method = TwoFactorMethodEnum.TOTP
        user.two_factor_enabled = True
        user.two_factor_confirmed_at = datetime.now(timezone.utc)
        await self.users.update(user)
        await self.session.commit()

    async def _confirm_email_setup(self, user: User, code: str) -> None:
        await self._verify_email_code(user, code, TwoFactorPurposeEnum.SETUP)

        user.two_factor_method = TwoFactorMethodEnum.EMAIL
        user.two_factor_enabled = True
        user.two_factor_confirmed_at = datetime.now(timezone.utc)
        user.totp_secret_encrypted = None
        await self.users.update(user)
        await self.session.commit()

    def _verify_totp_code(self, user: User, code: str) -> None:
        if not user.totp_secret_encrypted:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid authentication code")
        secret = decrypt_secret(user.totp_secret_encrypted)
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid authentication code")

    async def _issue_and_send_email_code(self, user: User, purpose: TwoFactorPurposeEnum) -> None:
        await self.email_otp_tokens.invalidate_all(user.id, purpose)

        code = generate_numeric_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.two_factor_challenge_expire_minutes)
        otp_token = EmailOtpToken(
            user_id=user.id,
            code_hash=hash_token(f"{user.id}:{code}"),
            purpose=purpose,
            expires_at=expires_at,
        )
        await self.email_otp_tokens.create(otp_token)
        await self.session.commit()

        await email_service.send_two_factor_code_email(user.email, user.first_name, code)

    async def _verify_email_code(self, user: User, code: str, purpose: TwoFactorPurposeEnum) -> None:
        code_hash = hash_token(f"{user.id}:{code}")
        stored = await self.email_otp_tokens.find_valid_by_hash(user.id, purpose, code_hash)
        if stored is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired code")

        await self.email_otp_tokens.mark_used(stored)
        await self.session.commit()

    def _issue_challenge_token(
        self, user: User, token_type: str, extra_claims: dict | None = None
    ) -> str:
        return create_interim_token(
            subject=str(user.id),
            token_type=token_type,
            expire_minutes=settings.two_factor_challenge_expire_minutes,
            extra_claims=extra_claims,
        )

    def _decode_challenge_token(self, token: str, expected_type: str) -> dict:
        try:
            decoded = decode_access_token(token)
        except jwt.PyJWTError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired verification session")
        if decoded.get("type") != expected_type:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired verification session")
        return decoded

    async def _load_active_user(self, decoded_token: dict) -> User:
        try:
            user_id = uuid.UUID(decoded_token["sub"])
        except (KeyError, ValueError):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired verification session")

        user = await self.users.get_by_id(user_id)
        if user is None or not user.is_active or user.is_suspended:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired verification session")
        return user

    # -- Everything below is unchanged from before 2FA -------------------------------

    async def refresh(self, payload: RefreshTokenRequestDTO) -> TokenPairDTO:
        token_hash = hash_token(payload.refresh_token)
        stored_token = await self.refresh_tokens.get_active_by_hash(token_hash)

        if stored_token is None or stored_token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")

        user = await self.users.get_by_id(stored_token.user_id)
        if user is None or not user.is_active or user.is_suspended:
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

        user.hashed_password = await hash_password(payload.new_password)
        await self.reset_tokens.mark_used(stored_token)
        await self.refresh_tokens.revoke_all_for_user(user.id)
        await self.session.commit()

    async def _issue_token_pair(self, user: User, extended: bool = False) -> TokenPairDTO:
        access_token, expires_in = create_access_token(subject=str(user.id), extended=extended)

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
