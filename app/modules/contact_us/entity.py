import enum
from sqlalchemy import Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity
from app.modules.user.entity import PlatformEnum


class ContactUsCategoryEnum(str, enum.Enum):
    GENERAL = "general"
    MENTORSHIP = "mentorship"
    PRICING = "pricing"
    COURSES = "courses"
    ACCOUNT_SUPPORT = "account_support"
    PARTNERSHIP = "partnership"
    OTHER = "other"
    MENTOR_APPLICATION = "mentor_application"


# Human-readable names, matching the enquiry types on the public contact form.
CONTACT_CATEGORY_LABELS: dict[ContactUsCategoryEnum, str] = {
    ContactUsCategoryEnum.GENERAL: "General",
    ContactUsCategoryEnum.MENTORSHIP: "Mentorship",
    ContactUsCategoryEnum.PRICING: "Pricing",
    ContactUsCategoryEnum.COURSES: "Course Enquiry",
    ContactUsCategoryEnum.ACCOUNT_SUPPORT: "Account or Learning Support",
    ContactUsCategoryEnum.PARTNERSHIP: "Partnership or Organisational Enquiry",
    ContactUsCategoryEnum.OTHER: "Other",
    ContactUsCategoryEnum.MENTOR_APPLICATION: "Mentor Application",
}


class ContactUsMessage(BaseEntity):
    __tablename__ = "contact_us_messages"

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[PlatformEnum] = mapped_column(
        Enum(PlatformEnum, name="platform_enum", native_enum=True), nullable=False
    )
    category: Mapped[ContactUsCategoryEnum | None] = mapped_column(
        Enum(ContactUsCategoryEnum, name="contact_us_category_enum", native_enum=True), nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Path of the page whose form sent the message, e.g. "/contact" or
    # "/policy-and-advocacy", so admins can see where enquiries come from.
    source_page: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Extra answers from richer forms (e.g. the mentorship forms' country, stage
    # and pathway), as an ordered list of {"label": ..., "value": ...} pairs so the
    # admin can show them in the order the visitor saw them.
    details: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    @property
    def reference(self) -> str:
        """Short, human-friendly reference shown to the visitor and in the admin."""
        return reference_for(self.id)


def reference_for(message_id) -> str:
    return f"SWCL-{message_id.hex[:8].upper()}"
