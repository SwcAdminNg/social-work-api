import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class CertificateBorderStyleEnum(str, enum.Enum):
    CLASSIC = "CLASSIC"
    MODERN = "MODERN"
    NONE = "NONE"


class CertificateTemplate(BaseEntity):
    """A reusable certificate design an admin or instructor can configure and
    then assign (via `Course.certificate_template_id`) to one or more courses.

    `owner_id` is null for a "global" template created by an admin - those are
    visible to every instructor as ready-made options, mirroring how a course
    catalog works. An instructor's own templates are only visible/usable by
    that instructor (and admins)."""

    __tablename__ = "certificate_templates"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)

    # -- copy -------------------------------------------------------------
    title_text: Mapped[str] = mapped_column(String(150), nullable=False, default="Certificate of Completion")
    subtitle_text: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default="This certificate is proudly presented to"
    )
    # Rendered with placeholders: {student_name} {course_title} {completion_date}
    # {instructor_name} {organization_name}
    body_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=(
            "for successfully completing the course “{course_title}” "
            "on {completion_date}, demonstrating dedication and mastery of the material."
        ),
    )
    organization_name: Mapped[str] = mapped_column(String(150), nullable=False, default="Social Workers Academy")
    footer_text: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- signature block ----------------------------------------------------
    signature_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    signature_title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    signature_image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # -- branding / imagery ---------------------------------------------------
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # -- theme ----------------------------------------------------------------
    primary_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#0B3D2E")
    accent_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#D4AF37")
    background_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#FFFDF7")
    text_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#1F2937")
    font_family: Mapped[str] = mapped_column(String(50), nullable=False, default="Helvetica")
    border_style: Mapped[CertificateBorderStyleEnum] = mapped_column(
        Enum(CertificateBorderStyleEnum, name="certificate_border_style_enum", native_enum=True),
        nullable=False,
        default=CertificateBorderStyleEnum.CLASSIC,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class Certificate(BaseEntity):
    """An issued certificate for one student's completion of one course. Created
    once, the moment `UserCourseProgress.is_completed` first flips to True (see
    `CertificateService.ensure_issued`, called from `LearningService._recalculate_progress`).
    The rendered PDF is generated lazily on first download/verify and then cached
    in `pdf_url`, since most completions are never actually downloaded."""

    __tablename__ = "certificates"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_certificates_user_course"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("certificate_templates.id", ondelete="SET NULL"), nullable=True
    )
    certificate_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    verification_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    recipient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    course_title: Mapped[str] = mapped_column(String(255), nullable=False)
