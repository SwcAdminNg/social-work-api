import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class FAQCategory(BaseEntity):
    __tablename__ = "faq_categories"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class FAQItem(BaseEntity):
    __tablename__ = "faq_items"

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("faq_categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class SupportTicketStatusEnum(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class SupportSenderTypeEnum(str, enum.Enum):
    """ADMIN means "staff side of the conversation" (any user `is_support_staff`
    accepts - an ADMIN, or an INSTRUCTOR who is a Support Desk member), not
    strictly `User.user_type == ADMIN`. See `app/modules/support/staff.py`."""

    USER = "USER"
    ADMIN = "ADMIN"


class SupportTicket(BaseEntity):
    """A user's help-desk ticket/chat with Support Desk staff. `escalated_at` gates
    the admin-notification email so it only fires once per unresponsive window (see
    `SupportService._check_and_maybe_escalate`) - it is cleared whenever an admin
    replies, so a ticket can escalate again if staff later go quiet on it too.
    Rating fields live directly on the ticket rather than a separate entity since
    it's a strict 1:1, terminal field set once on close - not a repeatable/child
    concept that would benefit from its own table."""

    __tablename__ = "support_tickets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SupportTicketStatusEnum] = mapped_column(
        Enum(SupportTicketStatusEnum, name="support_ticket_status_enum", native_enum=True),
        nullable=False,
        default=SupportTicketStatusEnum.OPEN,
        server_default=SupportTicketStatusEnum.OPEN.value,
    )
    assigned_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    last_user_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_admin_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    rated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportMessage(BaseEntity):
    """`body` may be an empty string for an attachment-only message (the
    DTO/service layer enforces that at least one of body/attachment is present -
    see `SupportMessageCreateDTO`). An attachment is uploaded directly to R2 via a
    presigned URL (see `/support/tickets/{id}/attachments/upload-url`) before the
    message referencing its `attachment_storage_key` is sent, same pattern as
    `CourseDocument`."""

    __tablename__ = "support_messages"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    sender_type: Mapped[SupportSenderTypeEnum] = mapped_column(
        Enum(SupportSenderTypeEnum, name="support_sender_type_enum", native_enum=True), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    attachment_storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attachment_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
