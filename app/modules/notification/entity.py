import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class NotificationTypeEnum(str, enum.Enum):
    # -- Account / auth ---------------------------------------------------------
    SIGNUP_WELCOME = "SIGNUP_WELCOME"
    LOGIN = "LOGIN"
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    PASSWORD_RESET_COMPLETED = "PASSWORD_RESET_COMPLETED"
    PROFILE_PICTURE_UPDATED = "PROFILE_PICTURE_UPDATED"
    TWO_FACTOR_ENABLED = "TWO_FACTOR_ENABLED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    ACCOUNT_UNSUSPENDED = "ACCOUNT_UNSUSPENDED"
    ROLE_CHANGED = "ROLE_CHANGED"

    # -- Payments -----------------------------------------------------------------
    PAYMENT_SUCCESSFUL = "PAYMENT_SUCCESSFUL"
    SUBSCRIPTION_RENEWED = "SUBSCRIPTION_RENEWED"
    SUBSCRIPTION_RENEWAL_FAILED = "SUBSCRIPTION_RENEWAL_FAILED"
    SUBSCRIPTION_EXPIRING_SOON = "SUBSCRIPTION_EXPIRING_SOON"
    SUBSCRIPTION_EXPIRED = "SUBSCRIPTION_EXPIRED"

    # -- Courses / learning ---------------------------------------------------------
    COURSE_ENROLLED = "COURSE_ENROLLED"
    COURSE_COMPLETED = "COURSE_COMPLETED"
    CERTIFICATE_ISSUED = "CERTIFICATE_ISSUED"
    LIVE_SESSION_SCHEDULED = "LIVE_SESSION_SCHEDULED"
    LIVE_SESSION_RESCHEDULED = "LIVE_SESSION_RESCHEDULED"
    LIVE_SESSION_REMINDER = "LIVE_SESSION_REMINDER"
    COURSE_REVIEW_REPLIED = "COURSE_REVIEW_REPLIED"

    # -- Community ------------------------------------------------------------------
    COMMUNITY_NEW_MESSAGE = "COMMUNITY_NEW_MESSAGE"

    # -- Support ----------------------------------------------------------------------
    SUPPORT_TICKET_MESSAGE = "SUPPORT_TICKET_MESSAGE"
    SUPPORT_TICKET_STATUS_CHANGED = "SUPPORT_TICKET_STATUS_CHANGED"
    SUPPORT_TICKET_ASSIGNED = "SUPPORT_TICKET_ASSIGNED"

    # -- Admin / back-office (recipient is an ADMIN) -----------------------------
    NEW_USER_SIGNUP = "NEW_USER_SIGNUP"
    NEW_PAYMENT = "NEW_PAYMENT"
    NEW_CONTACT_MESSAGE = "NEW_CONTACT_MESSAGE"
    NEW_SUPPORT_TICKET = "NEW_SUPPORT_TICKET"
    NEW_COURSE_REVIEW = "NEW_COURSE_REVIEW"
    ADMIN_INVITED = "ADMIN_INVITED"
    ADMIN_INVITE_ACCEPTED = "ADMIN_INVITE_ACCEPTED"


class Notification(BaseEntity):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[NotificationTypeEnum] = mapped_column(
        Enum(NotificationTypeEnum, name="notification_type_enum", native_enum=True), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Relative path (e.g. "/dashboard/certificates/{course_id}") so the same row
    # shape works for both the student and admin frontends - each prepends its
    # own origin when rendering the notification.
    link: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
