import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class PlatformEnum(str, enum.Enum):
    NG = "NG"
    COM = "COM"


class GenderEnum(str, enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


class UserTypeEnum(str, enum.Enum):
    USER = "USER"
    INSTRUCTOR = "INSTRUCTOR"
    ADMIN = "ADMIN"


class TwoFactorMethodEnum(str, enum.Enum):
    EMAIL = "EMAIL"
    TOTP = "TOTP"


class User(BaseEntity):
    __tablename__ = "users"

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    platform: Mapped[PlatformEnum] = mapped_column(
        Enum(PlatformEnum, name="platform_enum", native_enum=True), nullable=False
    )
    gender: Mapped[GenderEnum | None] = mapped_column(
        Enum(GenderEnum, name="gender_enum", native_enum=True), nullable=True
    )
    user_type: Mapped[UserTypeEnum] = mapped_column(
        Enum(UserTypeEnum, name="user_type_enum", native_enum=True),
        nullable=False,
        default=UserTypeEnum.USER,
        server_default=UserTypeEnum.USER.value,
    )
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile_picture_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Nullable to support admin-invited users: their row is created before they set
    # a password, via the invite-acceptance flow (see AdminInviteToken).
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Two-factor authentication. `two_factor_method` is null until the user completes
    # setup for the first time; every login is then required to go through setup
    # (see AuthService.login) until a method is confirmed.
    two_factor_method: Mapped[TwoFactorMethodEnum | None] = mapped_column(
        Enum(TwoFactorMethodEnum, name="two_factor_method_enum", native_enum=True), nullable=True
    )
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    # Encrypted (not hashed, since it must be decryptable to verify codes) TOTP seed.
    totp_secret_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    two_factor_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Instructor CV, kept up to date from their profile (distinct from the CV
    # submitted with their original InstructorApplication, which is immutable
    # application history). Nullable/optional for USER and ADMIN accounts too,
    # though only the instructor-profile endpoints let it be set.
    cv_storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cv_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class InstructorDocument(BaseEntity):
    """A named supporting document an instructor attaches to their profile (e.g.
    "License" -> the license PDF, "Certification" -> the certificate image).
    Unlike `User.cv_storage_key` (a single slot), an instructor can hold any
    number of these - each is its own row so it can be named, replaced and
    removed independently."""

    __tablename__ = "instructor_documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
