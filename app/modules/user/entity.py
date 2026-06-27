import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
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
    # Nullable to support admin-invited users: their row is created before they set
    # a password, via the invite-acceptance flow (see AdminInviteToken).
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
