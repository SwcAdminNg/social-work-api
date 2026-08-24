import re

from pydantic import EmailStr, Field, model_validator

from app.common.base_dto import BaseDTO, CreateDTO
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import PlatformEnum, TwoFactorMethodEnum, UserTypeEnum

OTP_CODE_PATTERN = r"^\d{6}$"

USERNAME_PATTERN = re.compile(r"^[a-z0-9_.]{3,30}$")


class SignUpRequestDTO(CreateDTO):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=30)
    email: EmailStr
    phone_number: str | None = Field(default=None, max_length=20)
    platform: PlatformEnum
    user_type: UserTypeEnum = UserTypeEnum.USER
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_username_and_passwords(self) -> "SignUpRequestDTO":
        if self.user_type == UserTypeEnum.ADMIN:
            raise ValueError(
                "Admin accounts cannot be created via sign-up; they must be invited by an existing admin"
            )

        if not USERNAME_PATTERN.match(self.username.lower()):
            raise ValueError(
                "Username must be 3-30 characters and contain only lowercase letters, "
                "numbers, dots, or underscores"
            )
        self.username = self.username.lower()

        if self.password != self.confirm_password:
            raise ValueError("Password and confirm_password do not match")
        return self


class LoginRequestDTO(BaseDTO):
    identifier: str = Field(min_length=1, description="Email address or username")
    password: str = Field(min_length=1)
    keep_logged_in: bool = Field(
        default=False, description="Issue a longer-lived access token"
    )


class ForgotPasswordRequestDTO(BaseDTO):
    email: EmailStr


class ResetPasswordRequestDTO(BaseDTO):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_passwords_match(self) -> "ResetPasswordRequestDTO":
        if self.new_password != self.confirm_password:
            raise ValueError("new_password and confirm_password do not match")
        return self


class RefreshTokenRequestDTO(BaseDTO):
    refresh_token: str = Field(min_length=1)


class TokenPairDTO(BaseDTO):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthSessionDTO(BaseDTO):
    user: UserReadDTO
    tokens: TokenPairDTO


class MessageDTO(BaseDTO):
    message: str


class TwoFactorChallengeDTO(BaseDTO):
    """Returned instead of a token pair when a login/signup can't complete yet because
    2FA setup or verification is still required."""

    challenge_token: str
    method: TwoFactorMethodEnum | None = Field(
        default=None, description="Set only when verification (not setup) is required"
    )


class LoginResponseDTO(BaseDTO):
    status: str = Field(
        description="'success', 'two_factor_setup_required', or 'two_factor_verification_required'"
    )
    session: AuthSessionDTO | None = None
    challenge: TwoFactorChallengeDTO | None = None


class TwoFactorSetupChallengeRequestDTO(BaseDTO):
    challenge_token: str = Field(min_length=1)


class TwoFactorSetupConfirmRequestDTO(BaseDTO):
    challenge_token: str = Field(min_length=1)
    code: str = Field(pattern=OTP_CODE_PATTERN, description="6-digit code")


class TwoFactorLoginVerifyRequestDTO(BaseDTO):
    challenge_token: str = Field(min_length=1)
    code: str = Field(pattern=OTP_CODE_PATTERN, description="6-digit code")


class TwoFactorLoginResendRequestDTO(BaseDTO):
    challenge_token: str = Field(min_length=1)


class TwoFactorConfirmCodeRequestDTO(BaseDTO):
    code: str = Field(pattern=OTP_CODE_PATTERN, description="6-digit code")


class TwoFactorTotpSetupResponseDTO(BaseDTO):
    secret: str = Field(description="Manual-entry key for the authenticator app")
    otpauth_url: str
    qr_code_data_uri: str = Field(description="data: URI PNG the client can render directly in an <img> tag")


class TwoFactorStatusDTO(BaseDTO):
    two_factor_enabled: bool
    two_factor_method: TwoFactorMethodEnum | None = None


class UsernameSuggestionsResponseDTO(BaseDTO):
    suggestions: list[str]


class UsernameAvailabilityResponseDTO(BaseDTO):
    username: str
    available: bool
