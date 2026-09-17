import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class InstructorApplicationStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InstructorApplication(BaseEntity):
    __tablename__ = "instructor_applications"

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Not unique: a rejected applicant is allowed to submit a new application later.
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    cv_storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    cv_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[InstructorApplicationStatusEnum] = mapped_column(
        Enum(InstructorApplicationStatusEnum, name="instructor_application_status_enum", native_enum=True),
        nullable=False,
        default=InstructorApplicationStatusEnum.PENDING,
        server_default=InstructorApplicationStatusEnum.PENDING.value,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once the application is approved and the (not-yet-activated) User row is created.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
