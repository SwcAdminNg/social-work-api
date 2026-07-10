import enum
from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity
from app.modules.user.entity import PlatformEnum


class ContactUsCategoryEnum(str, enum.Enum):
    GENERAL = "general"
    MENTORSHIP = "mentorship"
    PRICING = "pricing"
    COURSES = "courses"


class ContactUsMessage(BaseEntity):
    __tablename__ = "contact_us_messages"

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[PlatformEnum] = mapped_column(
        Enum(PlatformEnum, name="platform_enum", native_enum=True), nullable=False
    )
    category: Mapped[ContactUsCategoryEnum | None] = mapped_column(
        Enum(ContactUsCategoryEnum, name="contact_us_category_enum", native_enum=True), nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
