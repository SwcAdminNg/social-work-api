import re

from pydantic import EmailStr, Field, model_validator

from app.common.base_dto import BaseDTO, CreateDTO
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import PlatformEnum

USERNAME_PATTERN = re.compile(r"^[a-z0-9_.]{3,30}$")


class SignUpRequestDTO(CreateDTO):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=30)
    email: EmailStr
    phone_number: str | None = Field(default=None, max_length=20)
    platform: PlatformEnum
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_username_and_passwords(self) -> "SignUpRequestDTO":
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


class UsernameSuggestionsResponseDTO(BaseDTO):
    suggestions: list[str]


class UsernameAvailabilityResponseDTO(BaseDTO):
    username: str
    available: bool
